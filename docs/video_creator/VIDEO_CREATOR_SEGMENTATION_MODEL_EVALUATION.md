# Video Creator — segmentation model evaluation for Task 3.9D

## Decision

**MODNet is not enabled for product cutout.** The pinned model produces plausible portrait mattes for several photographs, but it also returns foreground mattes for non-person graphics and does not report a semantic class or a usable quality/confidence gate. Low-contrast/occluded input also has visible matte risk. A false positive could silently remove source-image content.

No cutout pipeline, Template Compiler feature, or Fall Diary 0.4 definition was added. `FALL_DIARY_CUTOUT_VERIFIED=false`.

## Candidate and setup

- Candidate: MODNet ONNX from `Xenova/modnet`, pinned revision `fa2fa546052fba4c08921230a26cc69a333fca12`.
- ONNX SHA-256: `07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9`; local file size approximately 25.9 MB.
- Runtime used for QA: ONNX Runtime 1.31.0, `CPUExecutionProvider`. Runtime install is local QA environment only; it was not added to product requirements.
- Model input used the pinned preprocessor configuration (short edge 512, dimensions divisible by 32, normalized RGB). It produced a 256-level soft alpha matte, then an RGBA diagnostic composite.
- Hardware inspection found an NVIDIA RTX 3060 Laptop GPU and PyTorch 2.6.0+cu126. This evaluation did not run ONNX GPU inference; GPU memory, latency, and GPU provider behavior remain unverified.
- Model code/weights are marked Apache-2.0 by the upstream MODNet project and pinned model card. That license does not grant rights to the private test images or the Muse soundtrack. See [MODNet repository](https://github.com/ZHKKKe/MODNet), [MODNet paper](https://ojs.aaai.org/index.php/AAAI/article/view/19999), and [pinned model card](https://huggingface.co/Xenova/modnet/tree/fa2fa546052fba4c08921230a26cc69a333fca12).

## Local QA results

The QA set has six private photo fixtures and two non-human fixtures. Times below are CPU inference time; foreground coverage counts pixels where alpha exceeds 0.05 and is diagnostic only, not a quality score.

| Fixture | Input | Time | Alpha >0.05 | Result / risk |
|---|---:|---:|---:|---|
| `photo_01.jpg` | 1536×2048 | 485 ms | 59.57% | Plausible portrait/hand silhouette; hair and hand edges still need visual review. |
| `photo_02.jpg` | 1536×2048 | 490 ms | 38.71% | Person is extracted, but bedding/occlusion and similar colors make mask correctness uncertain. |
| `photo_05.jpg` | 1364×2048 | 684 ms | 13.41% | Plausible full-body mask; thin/background details are not quality-scored. |
| `photo_07.jpg` | 1364×2048 | 690 ms | 17.39% | Plausible person mask against detailed foliage; not a semantic confidence result. |
| `photo_08.jpg` | 1536×2048 | 599 ms | 15.56% | Plausible seated-person matte; source contains ground/plant edges near the subject. |
| `photo_10.jpg` | 1151×2048 | 781 ms | 55.23% | Plausible portrait and hand, but hair/headphone boundaries remain visually sensitive. |
| `active_fox.jpg` | 554×554 | 446 ms | 36.28% | **False positive:** model makes a matte for a logo graphic; it cannot tell a person from a non-person. |
| `C04_leaf.png` | 512×512 | 410 ms | 16.70% | **False positive:** a non-human leaf icon receives a soft matte. |

The model emits alpha values but no structured class label, uncertainty estimate, rejection reason, or per-region quality score. On `active_fox.jpg` and `C04_leaf.png`, the returned mask looks structured enough to pass a superficial “non-empty mask” check. This rules out safe automatic acceptance based only on mask area or alpha range.

## Resources and failure behavior

- Measured CPU inference range: 410–781 ms per fixture at the tested inputs. This excludes app startup, media decode, upload, GPU transfer, caching, and export.
- Only CPU ONNX runtime was exercised. No GPU acceleration or memory limit was measured.
- Model file plus runtime are not part of the desktop package. Product download, version pinning, checksum verification, offline behavior, GPU fallback, cancellation, and model-cache eviction are not implemented.
- The experiment did not modify any source image. The output masks and RGBA files under `artifacts/video_creator/task3_9d/qa/modnet/` are local test evidence only.
- Since the runtime has no safe semantic/quality rejection signal, a production attempt must fail closed: keep the original binding and return an explicit reason; never silently treat an unverified rectangle or this model's non-empty matte as a cutout.

## Alternatives and next evaluation

Google MediaPipe Image Segmenter provides category/confidence masks for some supported models, including a selfie-focused model; that narrower capability could be evaluated with real portrait, pet, object, and busy-background fixtures. It was not integrated or benchmarked in this task. See the [official Image Segmenter guide](https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter) and [official selfie-segmentation model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Selfie%20Segmentation.pdf). A future acceptance must measure false positives, fine edges, occlusion, latency, GPU/CPU limits, and explicit failure behavior before adding a product dependency.

## Gate values

```text
SEGMENTATION_MODEL_EVALUATED=true
SEGMENTATION_MODEL_PRODUCT_APPROVED=false
AUTOMATIC_PERSON_SEGMENTATION_AVAILABLE=false
FALL_DIARY_CUTOUT_VERIFIED=false
```

