namespace MediaStudio.Desktop.Services;

public interface IImagePicker
{
    string? PickImage();
    string? PickSavePath(string defaultFileName, string format);
}
