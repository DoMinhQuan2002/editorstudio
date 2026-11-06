namespace MediaStudio.Desktop.Services;

public interface IMediaFilePicker
{
    IReadOnlyList<string> PickMediaFiles();
    string? PickSaveVideoPath(string defaultFileName);
}
