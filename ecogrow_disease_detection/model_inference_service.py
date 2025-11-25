from __future__ import annotations

import inspect
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests
import torch
from flask import Flask, jsonify, request
from PIL import Image
from torchvision import transforms
from peft import LoraConfig, LoraModel

from disease_detection.data.plant_data import make_segment_fn
from disease_detection.models.checkpoint_cache import ensure_mobileclip_checkpoint
from disease_detection.models.model_wrappers import (
    ConvNextDetector,
    ClipClassifierDetector,
    init_open_clip,
)
from disease_detection.preprocessing.image_segmentator import (
    black_bg_composite,
    crop_to_alpha_bbox,
    segment_plant_rgba,
)

app = Flask(__name__)

FAMILY_DISEASE_MAPPING = {
  "Asparagaceae": [
    "healthy",
    "anthracnose",
    "leaf_withering",
    "fungal_leaf_spot",
    "foliar_necrosis"
  ],
  "Araceae": [
    "healthy",
    "bacterial_wilt",
    "chlorosis",
    "manganese_toxicity"
  ],
  "Asteraceae": [
    "healthy",
    "bacterial_leaf_spot",
    "septoria_leaf_spot"
  ],
  "Malvaceae": [
    "healthy",
    "blight",
    "foliar_necrosis",
    "sun_scorch"
  ],
  "Rosaceae": [
    "healthy",
    "black_spot",
    "downy_mildew",
    "generic_insect_damage",
    "mosaic_virus",
    "mildew",
    "rust",
    "yellow_mosaic_virus"
  ],
  "Zingiberaceae": [
    "healthy",
    "aphids",
    "necrotic_fungal_lesion",
    "foliar_necrosis",
    "fungal_leaf_spot"
  ],
  "Asphodelaceae": [
    "healthy",
    "anthracnose",
    "generic_fungal_leaf_spot",
    "rust",
    "sun_scorch"
  ]
}

_FAMILY_DISEASES_NORMALIZED = {
    fam.lower(): {d.lower() for d in diseases}
    for fam, diseases in FAMILY_DISEASE_MAPPING.items()
}


DEFAULT_UNKNOWN_THRESHOLD = float(os.getenv("ECOGROW_UNKNOWN_THRESHOLD", "0.5"))


def _resolve_model_name() -> str:
    return os.getenv("ECOGROW_CLIP_MODEL_NAME", "MobileCLIP-S1")


def _resolve_pretrained_tag(model_name: str) -> str:
    env_override = os.getenv("ECOGROW_CLIP_PRETRAINED")
    if env_override:
        return env_override
    if model_name.startswith("MobileCLIP"):
        return ensure_mobileclip_checkpoint(model_name=model_name)
    return "laion2b_s34b_b79k"



MODEL_NAME = _resolve_model_name()
PRETRAINED_TAG = _resolve_pretrained_tag(MODEL_NAME)
SEGMENTATION_ENABLED = os.getenv("ECOGROW_SEGMENTATION", "0").lower() not in {"0", "false", "no"}
PAYLOAD_DIR = Path(os.getenv("ECOGROW_PAYLOAD_DIR", "artifacts/detectors")).expanduser()
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


@dataclass
class LoadedDetectorProfile:
    detector: object
    preprocess: Callable[[Image.Image], torch.Tensor]
    detector_type: str
    metadata: Dict[str, object]
    prompts_embeds: Optional[torch.Tensor] = None
    tokenized_prompts: Optional[torch.Tensor] = None
    text_features: Optional[torch.Tensor] = None


def _build_segmenter(enable: bool = SEGMENTATION_ENABLED):
    if not enable:
        return None
    return make_segment_fn(
        segment_plant_rgba,
        crop_to_alpha_bbox,
        black_bg_composite,
        pad=12,
    )


def _init_clip_components(
    model_name: str,
    pretrained_tag: str,
    device: torch.device,
):
    clip_model, preprocess, _, text_encoder = init_open_clip(
        model_name=model_name,
        pretrained_tag=pretrained_tag,
        device=device,
    )
    return clip_model, preprocess, text_encoder


def _build_clip_classifier_profile(
    profile_id: str,
    payload: dict,
    payload_path: Path,
    device: torch.device,
) -> LoadedDetectorProfile:

    classes = payload.get("classes")
    if not classes:
        raise ValueError(f"Detector payload '{payload_path.name}' missing 'classes'.")

    pretrained_tag = payload.get("pretrained_tag") 
    if pretrained_tag and Path(pretrained_tag).is_absolute() and not Path(pretrained_tag).exists():
        pretrained_tag = None
    if not pretrained_tag:
        pretrained_tag = _resolve_pretrained_tag(MODEL_NAME)

    clip_model, preprocess, text_encoder = _init_clip_components(MODEL_NAME, pretrained_tag, device)

    adapter = payload.get("lora_adapter")
    if adapter:
        cfg_dict = adapter.get("config") or {}
        state_dict = adapter.get("state_dict") or {}

        lora_cfg = LoraConfig(**cfg_dict)

        base_visual = clip_model.visual
        clip_model.visual = LoraModel(base_visual, lora_cfg, adapter_name="default")
        clip_model.visual.load_state_dict(state_dict, strict=False)

    clip_model.visual.to(device)

    prompts_embeds = payload.get("prompts_embeds")
    tokenized_prompts = payload.get("tokenized_prompts")
    text_features = payload.get("text_features")

    detector_kwargs: Dict[str, object] = {
        "classes": list(classes),
        "clip_model": clip_model,
        "preprocess": preprocess,
        "device": device,
        "feature_dropout": float(payload.get("dropout", 0.0)),
        "temperature": payload.get("temperature"),
        "text_encoder": text_encoder,
        "train_backbone": bool(payload.get("train_backbone", False)),
    }
    init_params = inspect.signature(ClipClassifierDetector.__init__).parameters
    if "detector_id" in init_params:
        detector_kwargs["detector_id"] = profile_id
    else:
        detector_kwargs["name"] = profile_id
    detector = ClipClassifierDetector(**detector_kwargs)

    state_dict = payload.get("model_state_dict")
    if state_dict is None:
        raise ValueError(f"Detector payload '{payload_path.name}' missing 'model_state_dict'.")
    detector.classifier.load_state_dict(state_dict, strict=True)

    metadata = {
        "pretrained_tag": pretrained_tag,
        "detector_type": "clip_classifier",
    }

    return LoadedDetectorProfile(
        detector=detector,
        preprocess=preprocess,
        detector_type="clip_classifier",
        metadata=metadata,
        prompts_embeds=prompts_embeds,
        tokenized_prompts=tokenized_prompts,
        text_features=text_features,
    )


def _build_convnext_profile(
    profile_id: str,
    payload: dict,
    device: torch.device,
) -> LoadedDetectorProfile:
    classes = payload.get("classes")
    if not classes:
        raise ValueError(f"ConvNeXt payload missing 'classes' for detector '{profile_id}'.")

    image_size = int(payload.get("image_size", 224))
    preprocess = _build_convnext_preprocess(image_size)

    detector_kwargs: Dict[str, object] = {
        "classes": list(classes),
        "pretrained": False,
        "device": device,
        "preprocess": preprocess,
        "train_backbone": False,
        "drop_rate": float(payload.get("dropout", 0.0)),
    }
    convnext_params = inspect.signature(ConvNextDetector.__init__).parameters
    if "detector_id" in convnext_params:
        detector_kwargs["detector_id"] = profile_id
    elif "name" in convnext_params:
        detector_kwargs["name"] = profile_id
    detector = ConvNextDetector(**detector_kwargs)
    state_dict = payload.get("model_state_dict")
    if state_dict is None:
        raise ValueError(f"ConvNeXt payload '{profile_id}' missing 'model_state_dict'.")
    detector.load_state_dict(state_dict, strict=True)

    metadata = {
        "image_size": image_size,
        "detector_type": "convnext",
    }

    return LoadedDetectorProfile(
        detector=detector,
        preprocess=preprocess,
        detector_type="convnext",
        metadata=metadata,
    )


def _build_convnext_preprocess(image_size: int):
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    return transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            normalize,
        ]
    )


class DiseaseInferenceService:
    """Local predictor that loads detector artifacts and runs detection via the model."""

    def __init__(
        self,
        payload_dir: Path = PAYLOAD_DIR,
        device: Optional[torch.device] = None,
        default_unknown_threshold: float = DEFAULT_UNKNOWN_THRESHOLD,
        enable_segmentation: bool = SEGMENTATION_ENABLED,
    ) -> None:
        self.device = device or DEVICE
        self.payload_dir = Path(payload_dir)
        self.segment_fn = _build_segmenter(enable_segmentation)
        self.detector_profile: Optional[LoadedDetectorProfile] = None
        self._load_detector_profile()
        self.default_unknown_threshold = float(default_unknown_threshold)

    def _load_detector_profile_from_dir(
        self,
        root: Path,
        device: torch.device,
    ) -> LoadedDetectorProfile:
        if not root.is_dir():
            raise RuntimeError(
                f"payload directory '{root}' not found. "
                "Set ECOGROW_PAYLOAD_DIR to a folder containing *.pt artifacts."
            )

        candidate_paths = sorted(root.glob("*.pt"))
        if not candidate_paths:
            raise RuntimeError(f"No *.pt detector payloads found in '{root}'.")

        path = candidate_paths[0]
        payload = torch.load(
            path,
            map_location="cpu",
            weights_only=False,  # detector payloads embed custom classes (e.g. LoRA configs)
        )
        profile_id = path.stem
        detector_type = payload.get("detector_type") or "clip_classifier"
        if detector_type == "clip_classifier":
            profile = _build_clip_classifier_profile(profile_id, payload, path, device)
        elif detector_type == "convnext":
            profile = _build_convnext_profile(profile_id, payload, device)
        else:
            raise ValueError(f"Unsupported detector_type '{detector_type}' in '{path.name}'.")

        profile.metadata["id"] = profile_id
        return profile

    def _load_detector_profile(self) -> None:
        self.detector_profile = self._load_detector_profile_from_dir(self.payload_dir, self.device)

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        processed = image.convert("RGB")
        if self.segment_fn is not None:
            processed = self.segment_fn(processed)
        return processed

    def _prepare_tensor(self, image: Image.Image, preprocess: Callable[[Image.Image], torch.Tensor]) -> torch.Tensor:
        tensor = preprocess(image)
        if not isinstance(tensor, torch.Tensor):
            raise TypeError("Detector preprocess must return a torch.Tensor.")
        if tensor.dim() == 3:
            tensor = tensor.unsqueeze(0)
        return tensor

    def _build_predict_kwargs(
        self,
        detector,
        *,
        unknown_threshold: float,
        restricted_diseases: Optional[List[str]],
    ) -> Dict[str, object]:
        predict_kwargs: Dict[str, object] = {"unknown_threshold": unknown_threshold}
        predict_params = set(inspect.signature(detector.predict).parameters)
        profile = self.detector_profile
        if profile is None:
            return predict_kwargs

        if profile.detector_type == "clip_classifier":
            if (
                "prompts_embeds" in predict_params
                and profile.prompts_embeds is not None
                and profile.tokenized_prompts is not None
            ):
                predict_kwargs["prompts_embeds"] = profile.prompts_embeds
                predict_kwargs["tokenized_prompts"] = profile.tokenized_prompts
            if "text_features" in predict_params and profile.text_features is not None:
                predict_kwargs["text_features"] = profile.text_features
            if "restricted_diseases" in predict_params and restricted_diseases:
                predict_kwargs["restricted_diseases"] = restricted_diseases
        elif profile.detector_type == "convnext" and restricted_diseases:
            if "restricted_classes" in predict_params:
                predict_kwargs["restricted_classes"] = restricted_diseases
            elif "restricted_indices" in predict_params:
                class_list = getattr(detector, "classes", None) or []
                idxs = [class_list.index(cls) for cls in restricted_diseases if cls in class_list]
                if idxs:
                    predict_kwargs["restricted_indices"] = idxs
        return predict_kwargs

    def _run(
        self,
        image: Image.Image,
        *,
        family: Optional[str] = None,
        disease_suggestions: Optional[List[str]] = None,
        unknown_threshold: Optional[float],
    ) -> Dict[str, object]:
        if self.detector_profile is None:
            raise RuntimeError("No detector profiles available.")
        restricted_diseases = self.restrict_diseases(family, disease_suggestions)
        thr = self.default_unknown_threshold if unknown_threshold is None else float(unknown_threshold)
        profile_id = self.detector_profile.metadata.get("id", "default")
        prepared_image = self._prepare_image(image)
        tensor = self._prepare_tensor(prepared_image, self.detector_profile.preprocess)
        detector = self.detector_profile.detector
  
        predict_kwargs = self._build_predict_kwargs(
            detector,
            unknown_threshold=thr,
            restricted_diseases=restricted_diseases,
        )
        with torch.no_grad():
            pred = detector.predict(tensor, **predict_kwargs)
        pred.setdefault("detector", profile_id)
        pred["detector_profile"] = profile_id
        pred["detector_type"] = self.detector_profile.detector_type
        preds: List[Dict[str, object]] = [pred]

        model_info = {
            "device": str(self.device),
            "detectors": [
                {
                    "id": profile_id,
                    "type": self.detector_profile.detector_type,
                }
            ],
        }

        temp_map: Dict[str, float] = {}
        temperature = getattr(self.detector_profile.detector, "temperature", None)
        if temperature is not None:
            temp_map[profile_id] = float(temperature)
        if temp_map:
            model_info["temperatures"] = temp_map

        return {
            "top_prediction": pred,
            "predictions": preds,
            "model": model_info,
        }

    def restrict_diseases(
        self, 
        family: str | None, 
        disease_suggestions: List[str] | None
    ) -> List[str] | None:
        classes = getattr(self.detector_profile.detector, "classes", None) if self.detector_profile else None
        if not classes:
            return disease_suggestions
        allowed = set(classes)
        if family:
            allowed &= set(FAMILY_DISEASE_MAPPING.get(family, allowed))
        if disease_suggestions:
            allowed &= set(disease_suggestions)

        if not allowed:
            return list(classes)
        return list(allowed)


    def predict_from_bytes(
        self,
        data: bytes,
        *,
        family: Optional[str] = None,
        disease_suggestions: Optional[List[str]] = None,
        unknown_threshold: Optional[float] = None,
    ) -> Dict[str, object]:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        return self._run(
            image,
            family=family,
            disease_suggestions=disease_suggestions,
            unknown_threshold=unknown_threshold,
        )

    def predict_from_url(
        self,
        url: str,
        *,
        timeout: float = 4.0,
        family: Optional[str] = None,
        disease_suggestions: Optional[List[str]] = None,
        unknown_threshold: Optional[float] = None,
    ) -> Dict[str, object]:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return self.predict_from_bytes(
            resp.content,
            family=family,
            disease_suggestions=disease_suggestions,
            unknown_threshold=unknown_threshold,
        )


def parse_unknown_threshold(raw_value) -> float:
    if raw_value is None:
        return DEFAULT_UNKNOWN_THRESHOLD
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:  # noqa: BLE001
        raise ValueError("unknown_threshold must be a float between 0 and 1.") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError("unknown_threshold must be between 0.0 and 1.0.")
    return value


def pick_param(body: Optional[dict], name: str, default=None):
    if isinstance(body, dict) and name in body:
        return body.get(name, default)
    return default


_SERVICE: Optional[DiseaseInferenceService] = DiseaseInferenceService()


def get_disease_inference_service() -> DiseaseInferenceService:
    """Singleton accessor for local model inference."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = DiseaseInferenceService()
    return _SERVICE


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200


def _parse_disease_suggestions(body: Optional[dict]) -> List[str] | None:
    suggestions: List[str] = []
    if request.values:
        suggestions.extend([v for v in request.values.getlist("disease_suggestions") if v])
    if isinstance(body, dict):
        raw = body.get("disease_suggestions")
        if isinstance(raw, list):
            suggestions.extend([str(v) for v in raw if v is not None])
    return suggestions or None


@app.route("/predict", methods=["POST"])
def predict_route():
    if "image" not in request.files:
        return jsonify({"error": "Missing 'image' file in request."}), 400

    file_bytes = request.files["image"].read()
    body = request.get_json(silent=True) if request.is_json else None

    raw_thr = request.values.get("unknown_threshold")
    if raw_thr is None and isinstance(body, dict):
        raw_thr = body.get("unknown_threshold")
    try:
        unknown_threshold = parse_unknown_threshold(raw_thr)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    family = request.values.get("family") or (body.get("family") if isinstance(body, dict) else None)
 
    disease_suggestions = _parse_disease_suggestions(body)
    service = get_disease_inference_service()
    try:
        result = service.predict_from_bytes(
            file_bytes,
            family=family,
            disease_suggestions=disease_suggestions,
            unknown_threshold=unknown_threshold,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Inference failed: {exc}"}), 500

    return jsonify({"status": "success", "data": result}), 200
