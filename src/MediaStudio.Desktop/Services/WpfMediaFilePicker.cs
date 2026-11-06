using Microsoft.Win32;

namespace MediaStudio.Desktop.Services;

public sealed class WpfMediaFilePicker : IMediaFilePicker
{
    public IReadOnlyList<string> PickMediaFiles()
    {
        var dialog = new OpenFileDialog
        {
            Title = "Thêm ảnh hoặc video",
            Filter = "Ảnh và video|*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff;*.webp;*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v|Tất cả tệp|*.*",
            CheckFileExists = true,
            Multiselect = true
        };

        return dialog.ShowDialog() == true ? dialog.FileNames : [];
    }

    public string? PickSaveVideoPath(string defaultFileName)
    {
        var dialog = new SaveFileDialog
        {
            Title = "Lưu video đã xuất",
            FileName = defaultFileName,
            DefaultExt = ".mp4",
            AddExtension = true,
            OverwritePrompt = true,
            Filter = "Video MP4|*.mp4"
        };
        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }
}
