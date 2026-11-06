namespace MediaStudio.Desktop.Services;

public enum MediaAssetType
{
    Video,
    Image,
    Audio,
    Unsupported
}

/// <summary>
/// Resolves backend-validated media metadata independently from any editor or timeline UI.
/// Filename suffixes do not determine the kind of an imported asset.
/// </summary>
public static class MediaTypeResolver
{
    public static MediaAssetType Resolve(VideoMediaDto? media)
    {
        if (media is null) return MediaAssetType.Unsupported;

        return media.Kind.Trim().ToLowerInvariant() switch
        {
            "video" when !string.IsNullOrWhiteSpace(media.VideoCodec) => MediaAssetType.Video,
            "image" when media.Width is > 0 && media.Height is > 0 => MediaAssetType.Image,
            "audio" when !string.IsNullOrWhiteSpace(media.AudioCodec) => MediaAssetType.Audio,
            _ => MediaAssetType.Unsupported
        };
    }
}
