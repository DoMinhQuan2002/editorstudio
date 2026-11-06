using Microsoft.Win32;

namespace MediaStudio.Desktop.Services;

public sealed class WpfImagePicker : IImagePicker
{
    public string? PickImage()
    {
        var dialog = new OpenFileDialog
        {
            Title = "Chọn ảnh",
            Filter = "Tệp hình ảnh|*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff|Tất cả tệp|*.*",
            CheckFileExists = true,
            Multiselect = false
        };

        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }

    public string? PickSavePath(string defaultFileName, string format)
    {
        var extension = format.ToUpperInvariant() switch
        {
            "SVG" => ".svg",
            "JPG" => ".jpg",
            "TIFF" => ".tif",
            _ => ".png"
        };
        var dialog = new SaveFileDialog
        {
            Title = format.Equals("SVG", StringComparison.OrdinalIgnoreCase) ? "Lưu ảnh vector" : "Lưu ảnh đã xử lý",
            FileName = defaultFileName,
            DefaultExt = extension,
            AddExtension = true,
            OverwritePrompt = true,
            Filter = format.ToUpperInvariant() switch
            {
                "SVG" => "SVG vector|*.svg",
                "JPG" => "JPEG image|*.jpg;*.jpeg",
                "TIFF" => "TIFF image|*.tif;*.tiff",
                _ => "PNG image|*.png"
            }
        };
        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }
}
