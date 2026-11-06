using System.Text.Json.Serialization;

namespace MediaStudio.Desktop.Services;

public sealed class VideoTemplateDto
{
    public string TemplateId { get; set; } = "";
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public string Category { get; set; } = "";
    public int DurationMs { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
    public string AspectRatio { get; set; } = "";
    public int SceneCount { get; set; }
    public int RequiredMediaSlots { get; set; }
    public string? PosterPath { get; set; }
    public string? PreviewSource { get; set; }
    public string AvailabilityStatus { get; set; } = "REFERENCE_ONLY";
    public string? TemplateDefinitionVersion { get; set; }
    public string? PosterSource { get; set; }
    public string? DemoSource { get; set; }
    public List<string> RenderCapabilities { get; set; } = [];
    public List<VideoTemplateMediaSlotRequirementDto> MediaSlotRequirements { get; set; } = [];
    public bool IsNew { get; set; }
    public bool PreviewAvailable { get; set; }
    public List<VideoTemplateSceneDto> Scenes { get; set; } = [];
    /// <summary>"video" (composition pipeline) or "image-set" (photo story: one image per page).</summary>
    public string OutputKind { get; set; } = "video";
    public bool IsImageSet => OutputKind == "image-set";
}

public sealed class VideoTemplateMediaSlotRequirementDto
{
    public int DurationMs { get; set; }
    public string SlotId { get; set; } = "";
    public List<string> AllowedMediaKinds { get; set; } = [];
    public bool Required { get; set; }
    public string ReusePolicy { get; set; } = "allow";
    public string MissingSlotPolicy { get; set; } = "error";
}

public sealed class VideoTemplateSceneDto
{
    public string Name { get; set; } = "";
    public int DurationMs { get; set; }
}

public sealed class VideoMediaDto
{
    public string AssetId { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Kind { get; set; } = "";
    public string ContentType { get; set; } = "";
    public long ByteSize { get; set; }
    public int? DurationMs { get; set; }
    public int? Width { get; set; }
    public int? Height { get; set; }
    public string? VideoCodec { get; set; }
    public string? AudioCodec { get; set; }
    public bool ThumbnailAvailable { get; set; }
}

public sealed class VideoProjectDto
{
    public int SchemaVersion { get; set; } = 2;
    public string ProjectId { get; set; } = "";
    public string TemplateId { get; set; } = "";
    public string Title { get; set; } = "";
    public int Width { get; set; }
    public int Height { get; set; }
    public int Fps { get; set; }
    public int FrameRateNumerator { get; set; } = 30;
    public int FrameRateDenominator { get; set; } = 1;
    public long Timebase { get; set; } = 90000;
    public List<VideoTimelineTrackDto> Tracks { get; set; } = [];
    public List<VideoClipDto> Clips { get; set; } = [];
    public List<VideoTextLayerDto> TextLayers { get; set; } = [];
    public List<VideoAudioTrackDto> AudioTracks { get; set; } = [];
    public Dictionary<string, object?> TemplateMetadata { get; set; } = [];
    public Dictionary<string, object?> Extensions { get; set; } = [];
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    public int Revision { get; set; }
}

public sealed class VideoTimelineTrackDto
{
    public string TrackId { get; set; } = "";
    public string Kind { get; set; } = "visual";
    public int LayerOrder { get; set; }
    public string DisplayName { get; set; } = "";
    public VideoTimelineTrackStateDto State { get; set; } = new();
    public List<VideoTimelineClipDto> Clips { get; set; } = [];
}

public sealed class VideoTimelineTrackStateDto
{
    public bool Visible { get; set; } = true;
    public bool Locked { get; set; }
    public bool Muted { get; set; }
    public bool Solo { get; set; }
}

public sealed class VideoTimelineClipDto
{
    public string ClipId { get; set; } = "";
    public string TrackId { get; set; } = "";
    public string ClipKind { get; set; } = "visual";
    public long TimelineStartTicks { get; set; }
    public long SourceStartTicks { get; set; }
    public long DurationTicks { get; set; }
    public string? MediaId { get; set; }
    public Dictionary<string, object?> Properties { get; set; } = [];
    public Dictionary<string, object?> TemplateMetadata { get; set; } = [];
}

public sealed class VideoClipDto
{
    public string ClipId { get; set; } = "";
    public string TrackId { get; set; } = "";
    public string ClipKind { get; set; } = "visual";
    public long TimelineStartTicks { get; set; }
    public long SourceStartTicks { get; set; }
    public long DurationTicks { get; set; }
    public string Name { get; set; } = "";
    public string? MediaId { get; set; }
    public int SourceStartMs { get; set; }
    public int DurationMs { get; set; }
    public string FitMode { get; set; } = "cover";
    public double PositionX { get; set; }
    public double PositionY { get; set; }
    public double Scale { get; set; } = 1;
    public double Rotation { get; set; }
    public string Effect { get; set; } = "none";
    public double Opacity { get; set; } = 1;
    public double AudioVolume { get; set; } = 1;
    public string Transition { get; set; } = "cut";
    public int TransitionDurationMs { get; set; }
}

public sealed class VideoTextLayerDto
{
    public string LayerId { get; set; } = "";
    public string TrackId { get; set; } = "";
    public long TimelineStartTicks { get; set; }
    public long DurationTicks { get; set; }
    public string Text { get; set; } = "";
    public int StartMs { get; set; }
    public int DurationMs { get; set; }
    public double X { get; set; }
    public double Y { get; set; }
    public int FontSize { get; set; }
    public string Color { get; set; } = "#FFFFFF";
    public string FontFamily { get; set; } = "Arial";
    public double Opacity { get; set; } = 1;
}

public sealed class VideoAudioTrackDto
{
    // TrackId remains the legacy audio-item identity used by current WPF commands.
    public string TrackId { get; set; } = "";
    public string ClipId { get; set; } = "";
    public string LaneTrackId { get; set; } = "";
    public long TimelineStartTicks { get; set; }
    public long SourceStartTicks { get; set; }
    public long DurationTicks { get; set; }
    public string MediaId { get; set; } = "";
    public int TimelineStartMs { get; set; }
    public int SourceStartMs { get; set; }
    public int DurationMs { get; set; }
    public double Volume { get; set; } = 1;
    public int FadeInMs { get; set; }
    public int FadeOutMs { get; set; }
}

public sealed class VideoWaveformDto
{
    public List<double> Samples { get; set; } = [];
}

public sealed class VideoRenderJobDto
{
    public string JobId { get; set; } = "";
    public string ProjectId { get; set; } = "";
    public string State { get; set; } = "";
    public int Progress { get; set; }
    public string Stage { get; set; } = "";
    public string? OutputFileName { get; set; }
    public string? OutputPath { get; set; }
    public string? ErrorCode { get; set; }
    public string? Error { get; set; }
    public VideoExportResultDto? ExportResult { get; set; }
}

public sealed class VideoCreatorExportCapabilitiesDto
{
    public bool CanExport { get; set; }
    public string? ErrorMessage { get; set; }
    public string DraftProjectId { get; set; } = "";
    public int DraftRevision { get; set; }
    public string TemplateId { get; set; } = "";
    public string? TemplateVersion { get; set; }
    public string CompositionFingerprint { get; set; } = "";
    public string CompositionReference { get; set; } = "";
    public Dictionary<string, string> MediaBindings { get; set; } = [];
    public int Width { get; set; }
    public int Height { get; set; }
    public int FrameRateNumerator { get; set; }
    public int FrameRateDenominator { get; set; } = 1;
    public long DurationTicks { get; set; }
    public long Timebase { get; set; } = 90_000;
    public List<string> Qualities { get; set; } = [];
    public string Format { get; set; } = "mp4";
    public string VideoCodec { get; set; } = "h264";
    public string? AudioCodec { get; set; }
    public bool HasAudio { get; set; }
    public bool SupportsCancel { get; set; }
}

public sealed class VideoCreatorExportRequestDto
{
    public string RequestId { get; set; } = "";
    public int DraftRevision { get; set; }
    public string TemplateId { get; set; } = "";
    public string TemplateVersion { get; set; } = "";
    public string CompositionFingerprint { get; set; } = "";
    public Dictionary<string, string> MediaBindings { get; set; } = [];
    public string Quality { get; set; } = "standard";
    public string OutputDirectory { get; set; } = "";
    public string FileName { get; set; } = "";
    public bool Overwrite { get; set; }
}

public sealed class VideoExportResultDto
{
    public string OutputPath { get; set; } = "";
    public long DurationMs { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
    public int FrameRateNumerator { get; set; }
    public int FrameRateDenominator { get; set; } = 1;
    public string Format { get; set; } = "";
    public string VideoCodec { get; set; } = "";
    public string? AudioCodec { get; set; }
    public long SizeBytes { get; set; }
    public bool FullDecodePassed { get; set; }
    public string JobId { get; set; } = "";
    public string DraftProjectId { get; set; } = "";
    public int DraftRevision { get; set; }
    public string TemplateId { get; set; } = "";
    public string? TemplateVersion { get; set; }
    public string CompositionFingerprint { get; set; } = "";
    public Dictionary<string, object?> OutputSettings { get; set; } = [];
}

public sealed class TemplateProcessingJobDto
{
    public string JobId { get; set; } = "";
    public string JobStatus { get; set; } = "QUEUED";
    public string? TemplateId { get; set; }
    public string? TemplateVersion { get; set; }
    public string? SelectionSessionId { get; set; }
    public string? BindingFingerprint { get; set; }
    public string? CurrentStage { get; set; }
    public int? ProgressPercent { get; set; }
    public string? ErrorCode { get; set; }
    public string? Error { get; set; }
    public string? ErrorMessage { get; set; }
    public string? DraftProjectId { get; set; }
    public string? CompositionReference { get; set; }
    public string? PreviewReference { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    public List<TemplateProcessingStageDto> Stages { get; set; } = [];
}

public sealed class TemplateProcessingStageDto
{
    public string StageId { get; set; } = "";
    public string Name { get; set; } = "";
    public string Status { get; set; } = "PENDING";
    public string? Message { get; set; }
    public string? ErrorCode { get; set; }
}

public sealed record VideoCompositionPreviewFrame(
    byte[] PngBytes,
    int GraphVersion,
    int FrameIndex,
    string SourceFingerprint,
    string Renderer,
    int ProjectRevision);

public sealed record VideoCompositionPreviewVideo(
    byte[] Mp4Bytes,
    int ProjectRevision,
    string SourceFingerprint);

public sealed class VideoEditorCapabilitiesDto
{
    public VideoFfmpegCapabilitiesDto Ffmpeg { get; set; } = new();
}

public sealed class VideoFfmpegCapabilitiesDto
{
    public bool Available { get; set; }
    public bool NativeVideoEngine { get; set; }
    public bool NativeAudioMixing { get; set; }
    public bool H264Encoding { get; set; }
    public bool AacEncoding { get; set; }
    public bool TextOverlay { get; set; }
    public string? FfmpegPath { get; set; }
    public string? Version { get; set; }
}

/// <summary>Data for moving one overlay live on the edit screen.</summary>
public sealed class VideoOverlayEditLayerDto
{
    public string ClipId { get; set; } = "";
    public int CanvasWidth { get; set; }
    public int CanvasHeight { get; set; }
    public string BackgroundPng { get; set; } = "";
    public string LayerPng { get; set; } = "";
    public double BaseLeft { get; set; }
    public double BaseTop { get; set; }
    public double BaseWidth { get; set; }
    public double BaseHeight { get; set; }
    public double[]? SubjectBox { get; set; }
    public double UserScale { get; set; } = 1;
    public double UserOffsetX { get; set; }
    public double UserOffsetY { get; set; }
}

public sealed class StoryRenderPageDto
{
    public int Index { get; set; }
    public string Path { get; set; } = "";
}

public sealed class StoryRenderResultDto
{
    public string TemplateId { get; set; } = "";
    public string TemplateDefinitionVersion { get; set; } = "";
    public string Directory { get; set; } = "";
    public List<StoryRenderPageDto> Pages { get; set; } = [];
}
