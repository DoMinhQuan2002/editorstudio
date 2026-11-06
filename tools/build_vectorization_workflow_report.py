from __future__ import annotations

import os
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Vectorization_V2_Workflow_and_Technology_Report.docx"

INK = "18212B"
MUTED = "536273"
ACCENT = "395B78"
TABLE_HEAD = "263C52"
TABLE_ALT = "F2F6F9"
CALLOUT = "EAF1F6"
WHITE = "FFFFFF"
RULE = "D7E0E7"
FONT = "Arial"


def set_cell_shading(cell, fill: str) -> None:
    props = cell._tc.get_or_add_tcPr()
    shd = props.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        props.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=90, start=110, bottom=90, end=110) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color=RULE, size="5") -> None:
    tbl = table._tbl
    props = tbl.tblPr
    borders = props.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        props.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)


def repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def prevent_row_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:cantSplit")
    tr_pr.append(node)


def set_run_font(run, size=10, color=INK, bold=None, italic=None, name=FONT) -> None:
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def set_paragraph_keep(paragraph, keep_next=False, keep_together=True) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    if keep_next:
        ppr.append(OxmlElement("w:keepNext"))
    if keep_together:
        ppr.append(OxmlElement("w:keepLines"))


def add_rich_paragraph(doc, parts, *, style=None, after=5, before=0, align=None):
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.line_spacing = 1.12
    if align is not None:
        p.alignment = align
    for part in parts:
        if isinstance(part, str):
            text, options = part, {}
        else:
            text, options = part
        run = p.add_run(text)
        set_run_font(run, options.get("size", 10), options.get("color", INK),
                     options.get("bold"), options.get("italic"))
    return p


def add_body(doc, text, *, after=5):
    p = doc.add_paragraph(style="Body Text")
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.12
    r = p.add_run(text)
    set_run_font(r, 10, INK)
    return p


def add_bullet(doc, label, text, *, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.paragraph_format.left_indent = Inches(0.22 + 0.22 * level)
    p.paragraph_format.first_line_indent = Inches(-0.13)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.08
    r = p.add_run(label)
    set_run_font(r, 9.7, ACCENT, bold=True)
    r = p.add_run(text)
    set_run_font(r, 9.7, INK)
    return p


def add_heading(doc, text, level=1):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    size = 16 if level == 1 else 12
    set_run_font(r, size, "000000", bold=True)
    return p


def add_callout(doc, title, text):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Inches(7.0)
    cell = table.cell(0, 0)
    cell.width = Inches(7.0)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_cell_shading(cell, CALLOUT)
    set_cell_margins(cell, top=135, bottom=135, start=170, end=170)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(title)
    set_run_font(r, 10, ACCENT, bold=True)
    p = cell.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.08
    r = p.add_run(text)
    set_run_font(r, 9.6, INK)
    set_table_borders(table, CALLOUT, "0")
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_table(doc, headers, rows, widths, *, font_size=8.7, header_font_size=8.8):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    repeat_table_header(table.rows[0])
    prevent_row_split(table.rows[0])
    for i, width in enumerate(widths):
        table.columns[i].width = Inches(width)
    for i, heading in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.width = Inches(widths[i])
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_shading(cell, TABLE_HEAD)
        set_cell_margins(cell)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(heading)
        set_run_font(r, header_font_size, WHITE, bold=True)
    for ridx, row_data in enumerate(rows):
        row = table.add_row()
        prevent_row_split(row)
        for cidx, value in enumerate(row_data):
            cell = row.cells[cidx]
            cell.width = Inches(widths[cidx])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
            if ridx % 2 == 1:
                set_cell_shading(cell, TABLE_ALT)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.04
            if isinstance(value, tuple):
                lead, body = value
                r = p.add_run(lead)
                set_run_font(r, font_size, ACCENT, bold=True)
                r = p.add_run(body)
                set_run_font(r, font_size, INK)
            else:
                r = p.add_run(str(value))
                set_run_font(r, font_size, INK)
        row.height = Inches(0.28)
    set_table_borders(table)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return table


def add_code_ref(doc, path, symbol):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.15)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(path)
    set_run_font(r, 8.4, ACCENT, bold=True, name="Consolas")
    r = p.add_run(f"  ·  {symbol}")
    set_run_font(r, 8.4, MUTED)


def add_page_number(section):
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_before = Pt(0)
    r = p.add_run("MediaStudio Vector V2  ·  ")
    set_run_font(r, 8, MUTED)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    p._p.append(field)


def main() -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.top_margin = Inches(0.62)
    section.bottom_margin = Inches(0.62)
    section.left_margin = Inches(0.67)
    section.right_margin = Inches(0.67)
    add_page_number(section)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal._element.rPr.rFonts.set(qn("w:ascii"), FONT)
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    body_style = styles["Body Text"]
    body_style.font.name = FONT
    body_style.font.size = Pt(10)
    body_style._element.rPr.rFonts.set(qn("w:ascii"), FONT)
    body_style._element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
    body_style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    for style_name in ("List Bullet", "List Bullet 2"):
        s = styles[style_name]
        s.font.name = FONT
        s.font.size = Pt(9.7)
        s._element.rPr.rFonts.set(qn("w:ascii"), FONT)
        s._element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
        s._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    for name, size in (("Heading 1", 16), ("Heading 2", 12)):
        s = styles[name]
        s.font.name = FONT
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = RGBColor.from_string("000000")
        s._element.rPr.rFonts.set(qn("w:ascii"), FONT)
        s._element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
        s._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        s.paragraph_format.space_before = Pt(8 if name == "Heading 1" else 5)
        s.paragraph_format.space_after = Pt(4)

    doc.core_properties.title = "Báo cáo cách thức hoạt động và công nghệ của chức năng chuyển ảnh sang vector"
    doc.core_properties.subject = "MediaStudio Vectorization V2"
    doc.core_properties.keywords = "MediaStudio, SVG, vectorization, WPF, Python, OpenCV"

    # Page 1: purpose and system map.
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("Báo cáo chức năng chuyển ảnh sang vector")
    set_run_font(r, 23, "000000", bold=True)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(12)
    r = p.add_run("Luồng xử lý và công nghệ đang dùng trong MediaStudio Vectorization V2")
    set_run_font(r, 11.5, MUTED)
    add_body(doc, "Báo cáo này mô tả cách chức năng đang chạy trong repository: người dùng thao tác ở desktop WPF, ảnh đi tới Python backend cục bộ, rồi được tách thành lớp nền, chữ, vùng đồ họa, đường Bézier và màu trước khi ghép thành SVG. Đây là mô tả implementation hiện tại, không phải thiết kế giả định hay danh sách công nghệ dự kiến.")
    add_callout(doc, "Tóm tắt", "Vector V2 không chỉ gọi một bộ trace ảnh. Pipeline dựng lại hình theo nhiều bước có kiểm soát: phân tích alpha và nền, nhận diện chữ, lập RegionGraph, fit đường cong, khôi phục gradient/chi tiết, rồi xác minh SVG có thể render. V2 đang là pipeline mặc định của API.")
    add_heading(doc, "Kiến trúc tổng thể", 1)
    flow = add_table(doc, ["1 · Desktop", "2 · API cục bộ", "3 · Python V2", "4 · SVG"], [[
        "C# WPF nhận ảnh và lệnh chạy.",
        "FastAPI tạo job và trả tiến độ.",
        "Các phase phân tích và dựng hình.",
        "Browser kiểm tra; WPF xem trước và lưu.",
    ]], [1.68, 1.68, 1.82, 1.82], font_size=8.5, header_font_size=8.4)
    add_body(doc, "WPF khởi động backend Python trên loopback 127.0.0.1 với cổng và token phiên chạy. Ảnh được gửi dưới dạng multipart; job chạy nền trong JobManager. Giao diện hỏi trạng thái job, tải kết quả SVG và dựng ảnh xem trước bằng Svg.Skia. API nhận và trả dữ liệu qua HTTP/JSON; không cần đưa ảnh lên dịch vụ web trong luồng vector hóa này.", after=2)
    add_heading(doc, "Phạm vi pipeline được mô tả", 2)
    add_bullet(doc, "Đường chạy production: ", "A → B → C → D1 → E1 → tái dựng chữ → SVG composer → render validation.")
    add_bullet(doc, "Các nhánh riêng: ", "Phase E2 có trong source nhưng không được production dispatcher gọi; VTracer/Potrace thuộc nhánh legacy, không phải bộ dựng hình của V2.")

    # Page 2: user/job flow and stage inventory.
    doc.add_page_break()
    add_heading(doc, "1. Từ thao tác người dùng đến kết quả SVG", 1)
    add_table(doc, ["Bước", "Việc xảy ra", "Giao diện nhận được"], [
        (("1. Chọn ảnh", ""), "WPF gửi ảnh tới `/api/v1/assets`; backend chuẩn hóa và lưu asset cho job.", "Thông tin asset và kích thước ảnh."),
        (("2. Bắt đầu", ""), "WPF gọi `/api/v1/vectorize/jobs` với engine=auto, mode=auto và text mode.", "Mã job; job chạy bất đồng bộ."),
        (("3. Theo dõi", ""), "WPF hỏi `/api/v1/jobs/{id}` khoảng mỗi 350 ms.", "Trạng thái, phần trăm và tên phase đang chạy."),
        (("4. Nhận kết quả", ""), "Khi job thành công, WPF tải `/api/v1/jobs/{id}/result`.", "Bytes SVG để preview và lưu ra đĩa."),
    ], [1.55, 3.65, 1.8], font_size=8.35)
    add_heading(doc, "Chuỗi xử lý trong backend", 2)
    add_table(doc, ["Giai đoạn", "Đầu vào → đầu ra", "Vai trò"], [
        ("Chuẩn hóa", "Ảnh gốc → RGBA và working canvas", "Chuẩn hướng EXIF, giới hạn bộ nhớ, giữ mapping kích thước."),
        ("A · Nền và alpha", "Ảnh → foreground RGBA", "Ước lượng nền và tạo matte có alpha mềm."),
        ("B · Chữ", "Foreground → text mask + graphic-only", "OCR, tách coverage chữ và ghi nhận vùng bị che."),
        ("C · Phân vùng", "Graphic-only → RegionGraph", "Tạo nhãn vùng, topology, lỗ và shared boundaries."),
        ("D1 · Hình học", "RegionGraph → paths Bézier", "Fit biên vùng; giữ góc và quan hệ biên chung."),
        ("E1 · Màu", "Paths + pixel nguồn → fills", "Chọn màu phẳng/gradient và lớp chi tiết được clip."),
        ("Ghép SVG", "Graphic + chữ → SVG", "Nối paths, gradients, clips; kiểm tra cấu trúc và render."),
    ], [1.35, 2.25, 3.4], font_size=8.25)
    add_callout(doc, "Lưu ý về kích thước", "Với ảnh lớn hơn giới hạn làm việc, V2 resize working canvas bằng Lanczos trước khi phân tích. SVG vẫn khai báo kích thước vật lý theo ảnh nguồn, còn viewBox dùng hệ tọa độ working canvas; upscale ảnh nguồn không tạo thêm chi tiết mới.")

    # Page 3: A/B/C technical details.
    doc.add_page_break()
    add_heading(doc, "2. Các phase tạo foreground và RegionGraph", 1)
    add_heading(doc, "Chuẩn hóa và Phase A — nền, alpha matte", 2)
    add_body(doc, "Pillow đọc ảnh, áp dụng EXIF orientation và chuyển sang RGBA. Production runner dùng working canvas tối đa 800 px cho cạnh dài; riêng mode fast dùng 554 px. Phase A kiểm tra alpha sẵn có; nếu ảnh còn nền đục, nó phân tích màu vùng biên, hỗ trợ màu Lab và kiểm tra connected component nối với mép ảnh. Một trường nền bậc hai được fit bằng least squares có trọng số để mô tả nền sáng tối không đều.")
    add_body(doc, "Từ xác suất nền, tương phản, độ mạnh cạnh và seed foreground/background, Phase A lập trimap rồi giải alpha matte cho dải khử răng cưa. Màu foreground ở biên được decontaminate theo mô hình trộn `I = alpha*F + (1-alpha)*B`, nhằm giảm viền nền cũ. Alpha gốc được giữ nếu ảnh đã có transparency. Giả định quan trọng là nền nối với biên tương đối phẳng hoặc biến thiên nhẹ; vật thể cùng màu và dính liền nền là trường hợp mơ hồ.")
    add_heading(doc, "Phase B — OCR và tách chữ khỏi artwork", 2)
    add_body(doc, "EasyOCR chạy CPU, nhận diện tiếng Anh và tiếng Việt. Reader được cache theo process và model nằm trong thư mục cục bộ của MediaStudio; nếu model chưa tồn tại, mã chuẩn bị tải model, kiểm checksum rồi mới khởi tạo reader. OCR trả polygon, nội dung và confidence. Phase B không dùng toàn bộ hộp OCR làm mask: nó ước lượng nền/màu chữ cục bộ, tạo glyph coverage theo chứng cứ màu và nét, phục hồi thành phần ký tự nhỏ, rồi tạo hai nhánh raster: text-only và graphic-only.")
    add_body(doc, "Pixel artwork nằm dưới vùng chữ không bị tự động inpaint. Phase B ghi nhận vùng che khuất để các phase sau biết phần nào không được xóa như chữ. Nếu OCR lỗi hoặc không có detection, mask chữ rỗng được trả cùng cảnh báo; chữ khi đó có thể còn trong nhánh graphic.")
    add_heading(doc, "Phase C — phân vùng có nhận biết cạnh", 2)
    add_body(doc, "OpenCV làm bilateral filter để giảm nhiễu cục bộ, đổi ảnh sang Lab và tính Sobel gradient. Các seed lấy từ lõi foreground, tránh hàng rào cạnh; marker-controlled watershed chia graphic thành các vùng ban đầu. Ranh yếu chỉ được merge khi edge strength, tỷ lệ cạnh cứng và chênh màu lân cận đều thấp. Vì vậy vùng màu không bị chia chỉ vì global quantization.")
    add_body(doc, "Kết quả là RegionGraph: mỗi region có mask, bbox, diện tích, màu, độ tương phản, gradient/edge score, importance, confidence và quan hệ cha/con; graph còn lưu lỗ, adjacency và shared boundaries. Các ứng viên detail/noise được đánh dấu để geometry và appearance cân nhắc; việc đánh dấu noise không đồng nghĩa xóa pixel. Phase C chưa tạo đường SVG.")
    add_callout(doc, "Công nghệ cốt lõi của A–C", "Python · Pillow · NumPy · OpenCV · EasyOCR. Lab/Sobel/watershed và connected components là xử lý ảnh cổ điển; EasyOCR là thành phần học máy chuyên nhận dạng chữ.")

    # Page 4: geometry, appearance, text and SVG.
    doc.add_page_break()
    add_heading(doc, "3. Dựng đường cong, màu và SVG", 1)
    add_heading(doc, "Phase D1 — đường biên thành Bézier", 2)
    add_body(doc, "D1 lấy contour và shared boundaries từ RegionGraph, phát hiện góc cấu trúc ở nhiều tỷ lệ, loại các ngoặt nhỏ do nhiễu, resample và denoise nhẹ từng span. Đường gần thẳng dùng một cubic biểu diễn đoạn thẳng; span cong được fit bằng recursive least-squares cubic Bézier, Newton reparameterization và thử gộp segment kề nhau. Shared boundary được lưu một lần trong geometry model và dùng xuôi/ngược cho hai region để giảm khe hở.")
    add_body(doc, "D1 kiểm tra cubic self-intersection bằng nghiệm giải tích trên hai tham số của cùng một đường cong, thay vì chỉ dựa vào giao cắt của mẫu raster. Nếu còn giao cắt, repair hiện tại chỉ refit đoạn contour nguồn ngắn nhất khớp hai anchor của cubic đó. Bản sửa phải qua metric guard về self-intersection, silhouette, boundary error, topology, shared gap và giới hạn anchor count; nếu không đạt thì rollback cục bộ. Cách này không hardcode tọa độ hay tên region của ACTIVE FOX.")
    add_heading(doc, "Phase E1 — khôi phục appearance", 2)
    add_body(doc, "E1 khóa geometry D1 rồi fit appearance theo từng region. Nó so sánh fill phẳng với gradient tuyến tính hoặc hướng tâm, dùng color samples, spatial profile và complexity penalty để tránh thêm gradient stops chỉ vì nhiễu JPEG. Với vùng màu thứ cấp có hỗ trợ đủ lớn, OpenCV k-means trong Lab tìm các cụm cục bộ; candidate chỉ giữ khi giảm Delta E đủ mức và được vẽ thành path clipped vào biên region. Mã không quantize toàn ảnh thành một bảng màu toàn cục.")
    add_body(doc, "Sau khi sinh SVG, E1 gọi Microsoft Edge hoặc Chrome ở chế độ headless để render thật, kiểm tra mapping tọa độ gradient, clip và sai khác giữa model prediction với ảnh render. Phase E2 có logic cross-validation/refit trên geometry đóng băng trong source, nhưng production dispatcher chỉ gọi E1 nên E2 không chạy cho mỗi job.")
    add_heading(doc, "Tái dựng chữ và ghép SVG", 2)
    add_body(doc, "Ở chế độ mặc định outlined, text được dựng từ glyph mask của ảnh nguồn thành SVG path; counters/lỗ chữ được giữ bằng fill-rule evenodd. Chế độ editable tìm font trong thư mục font Windows, đo IoU giữa glyph mask OCR và các ứng viên, rồi xuất `<text>`; font không khớp đủ tốt sẽ được đánh dấu approximate. Vì vậy outlined thường giữ hình dáng chữ trong ảnh tốt hơn, còn editable dễ sửa nội dung hơn.")
    add_body(doc, "SVG composer tạo nhóm graphic và typography, đổi ID, dọn definition không dùng, kiểm tra path không rỗng, ID/trỏ tham chiếu hợp lệ, viewBox đúng và không nhúng `<image>`. Production runner render toàn SVG lần cuối; nếu SVG parse được nhưng không tạo pixel alpha nhìn thấy, job bị báo lỗi thay vì trả file rỗng.")

    # Page 5: technology and configuration semantics.
    doc.add_page_break()
    add_heading(doc, "4. Công nghệ và ý nghĩa các chế độ", 1)
    add_table(doc, ["Công nghệ", "Vai trò thực tế trong chức năng"], [
        (("C# WPF · .NET 10", "  `net10.0-windows`"), "Desktop UI, MVVM command, trạng thái job, progress, preview và lưu SVG."),
        (("Svg.Skia 5.2.3", "  WPF"), "Rasterize SVG bytes thành ảnh preview trong desktop."),
        (("FastAPI · Uvicorn · Pydantic", "  Python backend"), "REST API cục bộ, xác thực token, schema request/response và job endpoints."),
        (("Pillow 11.2 · NumPy 1.26", "  nền tảng ảnh/số"), "Đọc, định hướng, resize Lanczos; mảng RGBA, thống kê màu và least squares."),
        (("OpenCV 4.11", "  computer vision"), "Lab, bilateral/Sobel, watershed, distance transform, contours, morphology và k-means."),
        (("EasyOCR 1.7.2", "  OCR"), "Nhận diện chữ EN/VI bằng CPU; dùng model cache cục bộ, có fallback/cảnh báo."),
        (("Shapely 2.1", "  kiểm geometry"), "Kiểm polygon/line validity trong các bước kiểm tra hình học; không sửa geometry production bằng make_valid."),
        (("SVG + ElementTree + Edge/Chrome", "  đầu ra"), "Sinh XML vector và render browser headless để xác nhận SVG thật sự nhìn thấy được."),
    ], [2.35, 4.65], font_size=8.3)
    add_heading(doc, "V2, legacy và tên chế độ", 2)
    add_bullet(doc, "V2 mặc định: ", "`create_app` chọn `MEDIASTUDIO_VECTORIZE_PIPELINE=v2` nếu biến môi trường không bị ghi đè. Kết quả job có metadata `vectorization_v2` để phân biệt với legacy.")
    add_bullet(doc, "VTracer/Potrace: ", "được gọi trong nhánh `run_legacy`; không phải thuật toán dựng hình của pipeline V2. Trong V2, engine=auto không tự chọn hai engine này.")
    add_bullet(doc, "Auto/Quality/Fast: ", "WPF hiện gửi `mode=auto`. V2 dùng working max dimension 554 px cho fast và 800 px cho các mode còn lại, gồm auto và quality. Trong source hiện tại, auto và quality chạy cùng chuỗi phase; `ai` là giá trị mode được chấp nhận nhưng chưa chọn một mô hình AI vector riêng.")
    add_bullet(doc, "Text mode: ", "mặc định outlined; editable thay đổi cách xuất chữ. Các trường color_count/simplification của hợp đồng API không điều khiển bộ dựng hình V2 hiện tại.")

    # Page 6: observed run, limits, source map.
    doc.add_page_break()
    add_heading(doc, "5. Kết quả production và giới hạn hiện tại", 1)
    add_body(doc, "Trong lượt kiểm tra production gần nhất với `images_upscaled_8x.png`, ảnh nguồn 4432 × 4432 px được phân tích ở working canvas 800 × 800 px. AUTO hoàn tất trong 59.566 giây; QUALITY trong 59.008 giây. Hai file SVG tạo ra giống nhau byte-for-byte ở lượt này. Metadata báo 17 visible vector paths, gồm 2 path chữ outlined, 12 gradients, không nhúng raster; cấu trúc SVG có 20 phần tử `<path>` tính cả các path định nghĩa/clip. D1 ghi nhận 0 self-intersection sau repair. Do canvas làm việc nhỏ hơn nguồn, API hiển thị thông tin `HIGH_RES_WORKING_DOWNSAMPLED`.")
    add_table(doc, ["Giới hạn", "Ảnh hưởng có thể gặp"], [
        ("Working canvas giới hạn 800 px (554 px fast)", "Nét rất mảnh hoặc chi tiết chỉ xuất hiện ở độ phân giải cao có thể mất trước khi trace. Kích thước SVG đầu ra không đồng nghĩa xử lý hình học ở 4432 px."),
        ("Giả định nền nối với biên", "Nền nhiều vật thể, nền có texture mạnh hoặc foreground cùng màu nền có thể tạo matte sai; xem warning/background confidence."),
        ("OCR cần model và vùng chữ nhận ra được", "Model được tải về cache khi chưa có; nếu model không khả dụng, Phase B fallback và chữ có thể đi theo nhánh artwork."),
        ("Font editable dựa trên font cài trên máy", "Font gốc không có trong Windows có thể được xấp xỉ. Outlined giữ glyph mask nhưng không còn là ký tự văn bản sửa trực tiếp."),
        ("Gradient/feature là mô hình gọn", "Ảnh có texture hoặc shading phức tạp được xấp xỉ bởi một số fill, stop và path; SVG hợp lệ không đảm bảo tái tạo từng pixel."),
    ], [2.15, 4.85], font_size=8.3)
    add_callout(doc, "Cách đọc kết quả", "SVG là các path và paint vector có thể mở/sửa trong trình chỉnh sửa SVG. Preview browser/WPF chứng minh tệp render được; fidelity còn phụ thuộc segmentation, OCR, giới hạn canvas và độ phức tạp của màu nguồn.")
    add_heading(doc, "Nguồn trong repository", 2)
    add_code_ref(doc, "src/MediaStudio.Desktop/ViewModels/ImageToolsViewModel.cs", "VectorizeToolViewModel.RunVectorizeAsync; RenderSvgPreview")
    add_code_ref(doc, "src/MediaStudio.Desktop/Services/MediaStudioApiClient.cs", "ImportImageAsync, StartVectorizeAsync, GetJobAsync, DownloadResultAsync, BackendProcessHost")
    add_code_ref(doc, "backend/mediastudio/api.py · backend/mediastudio/image_tools/vectorize.py", "create_app, vectorize job route, V2/legacy dispatcher")
    add_code_ref(doc, "backend/mediastudio/image_tools/vectorization_v2/production.py", "run_vectorization_v2 production order and progress stages")
    add_code_ref(doc, "backend/mediastudio/image_tools/vectorization_v2/{pipeline,background,phase_b,phase_c}.py", "Normalization, matte, OCR masks and RegionGraph")
    add_code_ref(doc, "backend/mediastudio/image_tools/vectorization_v2/{phase_d1,phase_e,phase_e1}.py", "Bézier geometry, appearance models, gradients and browser render")
    add_code_ref(doc, "backend/mediastudio/image_tools/vectorization_v2/{text_reconstruction,svg_composer}.py", "Outlined/editable text and SVG assembly checks")
    add_code_ref(doc, "backend/mediastudio/image_tools/vectorization/ocr_models.py", "EasyOCR model cache, checksum and CPU reader")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
