# Chức năng ứng dụng và model AI

Cập nhật: 06-11-2026. Tài liệu này ghi lại các luồng trong mã nguồn Media Studio và chỉ rõ phần nào dùng model học máy. Model được chạy cục bộ; các model cần thiết được tải từ nguồn upstream khi cài đặt hoặc khi dùng tính năng lần đầu. Ảnh/video đầu vào và đầu ra của người dùng không được đưa vào repository.

## Bản đồ chức năng

| Khu vực | Công dụng | Model / xử lý |
| --- | --- | --- |
| Image Tools — Nâng cấp ảnh | Phóng lớn ảnh thường hoặc ảnh anime ở các mức 2×, 4×, 8×; xem trước và lưu kết quả. | Real-ESRGAN (bảng dưới). Mức 8× gồm upscale AI 4× rồi resize Lanczos thêm 2×. |
| Image Tools — Ảnh sang vector | Phân tích ảnh raster và xuất SVG nhiều lớp; có thể nhận dạng và dựng lại chữ trong một số chế độ. | VTracer, Potrace, OpenCV là thuật toán/thư viện, không phải model AI. EasyOCR là tùy chọn cho nhận dạng chữ; IS-Net được dùng tùy chọn để tạo matte/tách nền. |
| Image Tools — Đường bế | Tạo contour ngoài, chỉnh vùng Giữ/Bỏ, đặt khoảng bù theo kích thước in và xuất SVG. | OpenCV/GrabCut và Pyclipper; không cần model sinh ảnh. Nhận dạng matte IS-Net có thể hỗ trợ xử lý nền phức tạp. |
| Video Creator | Dùng template, gán media vào các vị trí, xem trước và kết xuất video. Tách chủ thể khỏi ảnh overlay khi template yêu cầu lớp phủ. | BiRefNet kết hợp U²-Net Human Segmentation cho pipeline tách foreground trong composition; FFmpeg/native engine dựng và mã hóa video, không phải AI. |
| Fashion Studio | Chỉnh sửa ảnh theo mô tả: thử trang phục, đổi bối cảnh và chỉnh màu/chi tiết trang phục. | Qwen-Image-Edit-2511 qua PyTorch + Hugging Face Diffusers. |
| Media Library | Nhập, xem trước, quản lý media và kết quả cục bộ. | Không dùng model AI. |

## Model được dùng

| Model | Tính năng | Cách sử dụng trong ứng dụng | Nguồn và ghi chú giấy phép |
| --- | --- | --- | --- |
| **Qwen-Image-Edit-2511** | Fashion Studio | Chạy image-to-image có prompt và một hoặc nhiều ảnh đầu vào. Model mặc định là `Qwen/Qwen-Image-Edit-2511`; ứng dụng tải model khi người dùng yêu cầu. | [Model card chính thức](https://huggingface.co/Qwen/Qwen-Image-Edit-2511) ghi Apache-2.0. Tôn trọng các điều khoản và thông báo đi kèm model khi phân phối lại. |
| **RealESRGAN_x2plus** | Nâng cấp ảnh thường 2× | Model x2; file được kiểm tra SHA-256 trước khi nạp. | [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) và [release x2](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.1). Mã nguồn upstream ghi BSD-3-Clause; kiểm tra thông báo gắn với checkpoint trước khi phát hành lại trọng số. |
| **RealESRGAN_x4plus** | Nâng cấp ảnh thường 4×; là bước AI của chế độ 8× | Model x4; mức 8× thêm Lanczos 2× sau bước này. | [Release x4](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.1.0). |
| **RealESRGAN_x4plus_anime_6B** | Nâng cấp ảnh minh họa/anime 4× | Model x4 chuyên cho anime; file được kiểm tra SHA-256. | [Release anime 6B](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.2.4). |
| **BiRefNet General** (`birefnet-general`) | Tách foreground trên ảnh overlay của Video Creator | Tạo mask chủ thể tổng thể. Pipeline có thể hợp nhất thêm mask người để giữ phần tay/chân đang tương tác với vật thể. | Được gọi qua [rembg](https://github.com/danielgatis/rembg); checkpoint được lấy theo nguồn model mà rembg chỉ định. Giấy phép thư viện rembg không tự động áp dụng cho trọng số model; cần kiểm tra điều khoản của checkpoint trước khi mirror/phân phối. |
| **U²-Net Human Segmentation** (`u2net_human_seg`) | Bổ sung vùng người cho pipeline tách foreground của Video Creator | Tạo mask người; chỉ phần người chạm/gần foreground được giữ trong kết quả cuối. | Được tải qua rembg; kiểm tra giấy phép của checkpoint và nguồn upstream trước khi phân phối lại. |
| **IS-Net General Use** (`isnet-general-use`) | Tạo matte/tách nền tùy chọn trong vector hóa và xử lý artwork | Tạo mask nền/chủ thể khi pipeline chọn dùng matte; không phải model vector hóa. | Được tải qua rembg khi cần. Xác minh giấy phép của trọng số riêng trước khi mirror/phân phối. |
| **EasyOCR** (English reader) | Nhận dạng chữ trong luồng vector hóa được yêu cầu OCR | Nhận dạng dòng chữ để dựng lại chữ rõ hơn thay vì giữ toàn bộ chữ như nét trace. OCR không bắt buộc trong chế độ vector hóa mặc định. | [EasyOCR upstream](https://github.com/JaidedAI/EasyOCR). Mã thư viện và các model tải kèm có thể có thông báo riêng; kiểm tra upstream trước khi đóng gói. |

### Các công nghệ không phải model AI

- **VTracer/Potrace** chuyển ảnh raster thành đường path/vector; chúng không sinh hình bằng model học máy.
- **OpenCV/GrabCut** xử lý ảnh, mask và contour; **Pyclipper** bù đường cắt.
- **FFmpeg** cùng native video engine dựng filter graph, trộn âm thanh và mã hóa MP4.
- **Pillow, NumPy, PyTorch, ONNX Runtime, Diffusers** là thư viện/runtime. Chúng không phải các model trong bảng.

## Nơi lưu model và cách tải

- Trọng số Qwen hiện có trên máy phát triển nằm tại `D:\MediaStudio\models\Qwen-Image-Edit-2511` (73 file, khoảng **53.76 GiB** theo inventory ngày 06-11-2026). Đây là ổ dữ liệu riêng; trọng số không nằm trong repository. `download-qwen-model.bat` tải model chính thức từ Hugging Face vào `models\Qwen-Image-Edit-2511`. Backend cũng có thể tải model mặc định theo Hugging Face model ID khi được yêu cầu.
- Các model Real-ESRGAN được tải từ GitHub Releases vào thư mục model trong app data, ví dụ `%LOCALAPPDATA%\MediaStudio\models\realesrgan`.
- rembg và EasyOCR tải checkpoint/model của chúng vào cache model cục bộ khi tính năng tương ứng cần dùng. Người dùng cần kết nối Internet trong lần tải đầu; sau đó có thể chạy offline nếu đủ file và dependency.
- Không commit `.venv`, cache Hugging Face, cache Torch, database người dùng, media đầu vào/đầu ra, hay model weights vào Git thường. Giữ các script tải model, định danh phiên bản, URL và checksum trong source để có thể dựng lại môi trường.

## Phương án đưa model lớn lên Git

Model Qwen đang được chia shard safetensors; một số shard có kích thước khoảng **9.3 GiB**. GitHub Free/Pro Git LFS giới hạn mỗi file 2 GiB và đi kèm 10 GiB storage/bandwidth miễn phí, nên không thể đẩy nguyên bộ hiện có vào một repository GitHub thường hoặc Git LFS miễn phí. Các mức Team/Enterprise vẫn có giới hạn mỗi file, và LFS có thể phát sinh chi phí khi vượt quota. Xem [giới hạn Git LFS theo plan](https://docs.github.com/en/enterprise-cloud%40latest/repositories/working-with-files/managing-large-files/about-git-large-file-storage) và [quota Git LFS](https://docs.github.com/en/billing/concepts/product-billing/git-lfs).

Cách đóng gói phù hợp cho source repository là đẩy mã nguồn, tài liệu, script tải model và metadata/checksum; giữ trọng số Qwen tại model host upstream hoặc kho model có hỗ trợ file lớn. Nếu muốn lưu một bản mirror riêng, cần cung cấp URL kho model và xác nhận quota/chi phí trước khi tải lên. Không chia nhỏ trọng số thành nhiều file Git thủ công vì việc đó cần thêm bước ghép lại và kiểm tra tính toàn vẹn khi cài.

## Vị trí triển khai trong source

- `backend/mediastudio/fashion/engine.py` — nạp Qwen-Image-Edit.
- `backend/mediastudio/image_tools/upscale.py` — model Real-ESRGAN, URL tải và SHA-256.
- `backend/mediastudio/image_tools/text_rebuild.py` — EasyOCR tùy chọn.
- `backend/mediastudio/image_tools/layered_vector.py` — IS-Net qua rembg.
- `backend/mediastudio/video_editor/cutout.py` — BiRefNet + U²-Net Human Segmentation.
- `download-qwen-model.bat` — tải model Qwen từ nguồn chính thức.

