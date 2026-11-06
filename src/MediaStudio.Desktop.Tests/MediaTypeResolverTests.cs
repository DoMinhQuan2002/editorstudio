using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.Tests;

public sealed class MediaTypeResolverTests
{
    [Theory]
    [InlineData("video", "h264", "aac", MediaAssetType.Video)]
    [InlineData("audio", null, "mp3", MediaAssetType.Audio)]
    [InlineData("image", null, null, MediaAssetType.Image)]
    [InlineData("audio", null, null, MediaAssetType.Unsupported)]
    [InlineData("unknown", null, null, MediaAssetType.Unsupported)]
    public void MediaTypeUsesValidatedMetadata(string kind, string? videoCodec, string? audioCodec,
        MediaAssetType expected)
    {
        var media = new VideoMediaDto
        {
            Kind = kind,
            VideoCodec = videoCodec,
            AudioCodec = audioCodec,
            Width = kind == "image" ? 640 : null,
            Height = kind == "image" ? 480 : null
        };
        Assert.Equal(expected, MediaTypeResolver.Resolve(media));
    }

    [Fact]
    public void MissingMetadataIsUnsupported()
    {
        Assert.Equal(MediaAssetType.Unsupported, MediaTypeResolver.Resolve(null));
    }
}
