using System.IO;
using System.Windows.Media.Imaging;

namespace MediaStudio.Desktop.Services;

public interface IMediaSelectionService
{
    Task<IReadOnlyList<VideoMediaDto>> ListAsync();
    Task<VideoMediaDto> ImportAsync(string path);
    Task<byte[]> ThumbnailAsync(string id);
    Task DeleteFromLibraryAsync(IReadOnlyList<string> ids) => throw new NotSupportedException("Dịch vụ chưa hỗ trợ xóa media.");
    Task<string> PrepareAsync(string templateId, string version, Dictionary<string, string> bindings);
}

public sealed class MediaSelectionService(MediaStudioApiClient client) : IMediaSelectionService
{
    public Task<IReadOnlyList<VideoMediaDto>> ListAsync() => client.GetVideoMediaAsync();
    public Task<VideoMediaDto> ImportAsync(string path) => client.ImportVideoMediaAsync(path);
    public Task<byte[]> ThumbnailAsync(string id) => client.GetVideoMediaThumbnailAsync(id);
    public Task DeleteFromLibraryAsync(IReadOnlyList<string> ids) => client.DeleteVideoLibraryMediaAsync(ids);
    public Task<string> PrepareAsync(string id, string version, Dictionary<string, string> bindings) =>
        client.PrepareMediaSelectionAsync(id, version, bindings);

    public static BitmapImage DecodeThumbnail(byte[] bytes)
    {
        using var stream = new MemoryStream(bytes);
        var image = new BitmapImage();
        image.BeginInit();
        image.CacheOption = BitmapCacheOption.OnLoad;
        image.DecodePixelWidth = 320;
        image.StreamSource = stream;
        image.EndInit();
        image.Freeze();
        return image;
    }
}
