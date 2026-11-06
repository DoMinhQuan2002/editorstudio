# Fall Diary — foreground cutout investigation

## Gate

```text
FALL_DIARY_CUTOUT_VERIFIED = false
AUTOMATIC_PERSON_SEGMENTATION_AVAILABLE = false
```

Task 3.9B did not connect an unverified segmentation component to the template renderer. There is no mask/cutout layer in `0.2.0-motion-pilot`, and no rectangular image/card layer is described as cutout.

## Environment inspection

The backend runtime has `torch`, `cv2` and `PIL`. The following candidate automatic segmentation packages/runtime were absent at inspection: `rembg`, `transformers`, `mediapipe`, `ultralytics`, `transparent_background` and `onnxruntime`. Package presence for Torch/OpenCV alone does not provide a selected, versioned person-segmentation model or production-quality alpha matte.

The existing Foreground Protection Lab in `backend/mediastudio/image_tools/foreground_svg/protection_lab.py` is an experimental guided/manual alpha workflow with source/ROI and user-edit semantics. It is not an automatic person detector with confidence, model provenance and consistent soft hair/object edges. The vectorization segmentation algorithms are not repurposed as image background removal.

## Required future data flow

No part of the following pipeline is marked complete for Fall Diary:

```text
Source image + SHA-256
  → named/versioned segmentation model and configuration
  → confidence-gated soft alpha mask
  → RGBA derivative with source/mask provenance
  → cache key: source hash + model version + config version
  → explicit RGBA/mask clip in Project V2
  → shared preview/export transform and animation
```

Before integrating, validate a representative set of portrait, pet, object and busy-background photos. Record alpha edge quality, protected foreground details, transparent pixel count, source hash, model/config IDs, processing status and failure reason. Low confidence must keep the source image or ask for guided correction; it must not silently make a rectangle, infer a subject from one photo, or claim success.

## Alpha versus cutout

The shared renderer accepts actual alpha from an RGBA/transparent PNG as an input channel and the second QA set includes a translucent overlay fixture. Preserving source alpha does not create a new foreground segmentation mask. For this reason, the verified generic effect is **alpha compositing**, while the Fall Diary **cutout effect remains unsupported**.
