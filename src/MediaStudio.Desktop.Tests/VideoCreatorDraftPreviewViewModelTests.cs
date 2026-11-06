using System.IO;
using System.Text.Json;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Tests;

public sealed class VideoCreatorDraftPreviewViewModelTests
{
    [Fact]
    public async Task LoadUsesCompositionEventGroupsAndRequiresActualPlaybackOpen()
    {
        using var files = new TemporaryFiles();
        var service = new FakeDraftPreviewService(CreateProject(), files);
        var vm = new VideoCreatorDraftPreviewViewModel(service, service.Project.ProjectId,
            "denim-story", "1.0.0", () => { });

        await vm.LoadAsync();

        Assert.True(vm.IsReady);
        Assert.False(vm.IsPlaybackVerified);
        Assert.Equal(2, vm.Scenes.Count);
        Assert.Contains(vm.Scenes, scene => scene.EventId == "opening" && scene.StartTicks == 0);
        Assert.Contains(vm.Scenes, scene => scene.EventId == "second-look" && scene.StartTicks == 180_000);
        Assert.Equal(3, service.RenderedFrames.Count); // One current frame plus one for each compiled event.
        Assert.Equal(4, vm.DurationSeconds);
        Assert.Equal("9:16", vm.AspectRatioLabel);
        Assert.False(vm.CanGoNext);
        Assert.Equal("Màn 6 chưa được triển khai.", vm.NextDisabledReason);
        Assert.Equal(service.Project.ProjectId, vm.Handoff?.DraftProjectId);
        Assert.Equal(service.Project.Revision, vm.Handoff?.DraftRevision);

        vm.MarkPlaybackOpened(TimeSpan.FromSeconds(4));
        Assert.True(vm.IsPlaybackVerified);
        Assert.False(vm.CanGoNext); // The export screen is deliberately outside Task 3.6.
    }

    [Fact]
    public async Task LateSeekResponseCannotReplaceTheNewerCompositionFrame()
    {
        using var files = new TemporaryFiles();
        var service = new FakeDraftPreviewService(CreateProject(), files);
        var delayedFrame = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var delayedStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        service.BeforeFrame = async (ticks, _) =>
        {
            if (ticks == 90_000)
            {
                delayedStarted.SetResult();
                await delayedFrame.Task; // Simulate an in-flight renderer that cannot be cancelled.
            }
        };
        var vm = new VideoCreatorDraftPreviewViewModel(service, service.Project.ProjectId,
            "denim-story", "1.0.0", () => { });
        await vm.LoadAsync();

        var oldSeek = vm.SeekToAsync(1);
        await delayedStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));
        await vm.SeekToAsync(2);
        delayedFrame.SetResult();
        await oldSeek;

        Assert.Equal(180_000, vm.PreviewFrameTimestampTicks);
    }

    [Fact]
    public async Task SelectingSceneRequestsSeekOnThePlaybackPlayer()
    {
        using var files = new TemporaryFiles();
        var service = new FakeDraftPreviewService(CreateProject(), files);
        var vm = new VideoCreatorDraftPreviewViewModel(service, service.Project.ProjectId,
            "denim-story", "1.0.0", () => { });
        await vm.LoadAsync();
        vm.MarkPlaybackOpened(TimeSpan.FromSeconds(4));
        var requestedPositions = new List<TimeSpan>();
        vm.PlaybackSeekRequested += requestedPositions.Add;

        vm.SelectSceneCommand.Execute(vm.Scenes.Single(scene => scene.EventId == "second-look"));

        Assert.Equal(TimeSpan.FromSeconds(2), Assert.Single(requestedPositions));
    }

    [Fact]
    public async Task ApprovedDraftHandoffOpensScreen06WithCommittedRevisionAndPreview()
    {
        using var files = new TemporaryFiles();
        var service = new FakeDraftPreviewService(CreateProject(), files);
        Screen6DraftHandoff? opened = null;
        var vm = new VideoCreatorDraftPreviewViewModel(service, service.Project.ProjectId,
            "denim-story", "1.0.0", () => { }, openExport: handoff => opened = handoff);

        await vm.LoadAsync();
        vm.MarkPlaybackOpened(TimeSpan.FromSeconds(4));

        Assert.True(vm.CanGoNext);
        vm.NextCommand.Execute(null);
        Assert.NotNull(opened);
        Assert.Equal(service.Project.ProjectId, opened.DraftProjectId);
        Assert.Equal(service.Project.Revision, opened.DraftRevision);
        Assert.Equal("denim-story", opened.TemplateId);
        Assert.Equal("1.0.0", opened.TemplateVersion);
        Assert.Equal("graph-fingerprint", opened.CompositionFingerprint);
        Assert.True(File.Exists(opened.PreviewVideoPath));
        Assert.NotNull(opened.PreviewPoster);
        Assert.Equal(0, opened.PreviewPosterTimestampTicks);
        Assert.True(opened.PreviewPoster!.IsFrozen);
    }

    [Fact]
    public async Task MediaReplacementSavesOnlyMatchingSlotsIntoSameProjectAndReopensBindings()
    {
        using var files = new TemporaryFiles();
        var project = CreateProject();
        var unchangedClip = project.Tracks[0].Clips.Single(clip =>
            ReadString(clip.TemplateMetadata["eventId"]) == "second-look"
            && ReadString(clip.TemplateMetadata["slotId"]) == "detail");
        unchangedClip.SourceStartTicks = 45_000;
        project.Clips.Single(clip => clip.ClipId == unchangedClip.ClipId).SourceStartTicks = 45_000;
        var service = new FakeDraftPreviewService(project, files);
        var vm = new VideoCreatorDraftPreviewViewModel(service, project.ProjectId,
            "denim-story", "1.0.0", () => { });
        await vm.LoadAsync();
        var originalDetail = vm.MediaBindings["detail"];
        var unrelatedClipId = project.Tracks[0].Clips.Single(clip =>
            (string)clip.TemplateMetadata["eventId"]! == "second-look"
            && (string)clip.TemplateMetadata["slotId"]! == "detail").ClipId;

        await vm.ReplaceMediaAsync(new Dictionary<string, string>
        {
            ["hero"] = "f".PadLeft(32, 'f'),
            ["detail"] = originalDetail,
        });

        Assert.Equal(project.ProjectId, service.SavedProjects.Single().ProjectId);
        Assert.Equal(project.Revision + 1, vm.Revision);
        Assert.Equal("f".PadLeft(32, 'f'), vm.MediaBindings["hero"]);
        Assert.Equal(originalDetail, vm.MediaBindings["detail"]);
        Assert.Equal(45_000, service.Project.Tracks[0].Clips.Single(clip => clip.ClipId == unrelatedClipId).SourceStartTicks);
        var saved = service.Project;
        var changed = saved.Tracks.SelectMany(track => track.Clips).Where(clip =>
            ReadString(clip.TemplateMetadata["slotId"]) == "hero").ToArray();
        Assert.NotEmpty(changed);
        Assert.All(changed, clip => Assert.Equal("f".PadLeft(32, 'f'), clip.MediaId));
        Assert.Equal(originalDetail, saved.Clips.Single(clip => clip.ClipId == unrelatedClipId).MediaId);
        Assert.Equal("1.0.0", ReadString(saved.TemplateMetadata["templateDefinitionVersion"]));

        var reopened = new VideoCreatorDraftPreviewViewModel(service, project.ProjectId,
            "denim-story", "1.0.0", () => { });
        await reopened.LoadAsync();
        Assert.Equal(vm.Revision, reopened.Revision);
        Assert.Equal(vm.MediaBindings, reopened.MediaBindings);
        Assert.Equal("f".PadLeft(32, 'f'), reopened.MediaBindings["hero"]);
    }

    [Fact]
    public async Task AudioGainAndMuteAreSavedAsOneProjectRevisionAndReloaded()
    {
        using var files = new TemporaryFiles();
        var project = CreateProject(withAudio: true);
        var service = new FakeDraftPreviewService(project, files);
        var vm = new VideoCreatorDraftPreviewViewModel(service, project.ProjectId,
            "denim-story", "1.0.0", () => { });
        await vm.LoadAsync();

        Assert.True(vm.IsAudioSettingsAvailable);
        vm.PendingAudioVolume = 45;
        vm.PendingAudioMuted = true;
        Assert.True(vm.CanSaveDraft);
        await vm.SaveDraftCommand.ExecuteAsync();

        Assert.Equal(project.ProjectId, vm.ProjectId);
        Assert.Equal(project.Revision + 1, vm.Revision);
        Assert.Equal(0.45, service.Project.AudioTracks.Single().Volume, 2);
        Assert.True(service.Project.Tracks.Single(track => track.Kind == "audio").State.Muted);
        Assert.False(vm.CanSaveDraft);

        var reopened = new VideoCreatorDraftPreviewViewModel(service, project.ProjectId,
            "denim-story", "1.0.0", () => { });
        await reopened.LoadAsync();
        Assert.Equal(45, reopened.PendingAudioVolume);
        Assert.True(reopened.PendingAudioMuted);
    }

    [Fact]
    public async Task TextAndAudioControlsStayUnavailableWhenDefinitionHasNoEditableFieldOrTrack()
    {
        using var files = new TemporaryFiles();
        var project = CreateProject();
        var vm = new VideoCreatorDraftPreviewViewModel(new FakeDraftPreviewService(project, files), project.ProjectId,
            "denim-story", "1.0.0", () => { });

        await vm.LoadAsync();

        Assert.False(vm.IsAudioSettingsAvailable);
        Assert.Contains("không có audio track", vm.AudioUnavailableReason, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("không khai báo", vm.TextUnavailableReason, StringComparison.OrdinalIgnoreCase);
        Assert.False(vm.CanSaveDraft);
    }

    private static VideoProjectDto CreateProject(bool withAudio = false)
    {
        const string projectId = "a1111111111111111111111111111111";
        var firstTrackId = "b1111111111111111111111111111111";
        var audioTrackId = "c1111111111111111111111111111111";
        var visualClips = new[]
        {
            CreateTimelineClip("d1111111111111111111111111111111", firstTrackId, "opening", "hero", 0),
            CreateTimelineClip("e1111111111111111111111111111111", firstTrackId, "opening", "detail", 0),
            CreateTimelineClip("f1111111111111111111111111111111", firstTrackId, "second-look", "hero", 180_000),
            CreateTimelineClip("01111111111111111111111111111111", firstTrackId, "second-look", "detail", 180_000),
        };
        var tracks = new List<VideoTimelineTrackDto>
        {
            new()
            {
                TrackId = firstTrackId,
                Kind = "visual",
                DisplayName = "Template visual",
                Clips = visualClips.ToList(),
            },
        };
        var legacyClips = visualClips.Select((clip, index) => new VideoClipDto
        {
            ClipId = clip.ClipId,
            TrackId = firstTrackId,
            ClipKind = "image",
            TimelineStartTicks = clip.TimelineStartTicks,
            SourceStartTicks = clip.SourceStartTicks,
            DurationTicks = clip.DurationTicks,
            Name = $"slot-{index}",
            MediaId = clip.MediaId,
            SourceStartMs = (int)(clip.SourceStartTicks / 90),
            DurationMs = (int)(clip.DurationTicks / 90),
        }).ToList();
        var project = new VideoProjectDto
        {
            ProjectId = projectId,
            TemplateId = "denim-story",
            Title = "Denim Story",
            Width = 1080,
            Height = 1920,
            Fps = 30,
            FrameRateNumerator = 30,
            FrameRateDenominator = 1,
            Timebase = 90_000,
            Revision = 3,
            CreatedAt = DateTimeOffset.UtcNow.AddMinutes(-1),
            UpdatedAt = DateTimeOffset.UtcNow,
            Tracks = tracks,
            Clips = legacyClips,
            TemplateMetadata = new Dictionary<string, object?>
            {
                ["templateId"] = "denim-story",
                ["templateDefinitionVersion"] = "1.0.0",
                ["templateBindings"] = new Dictionary<string, string>
                {
                    ["hero"] = "1".PadLeft(32, '1'),
                    ["detail"] = "2".PadLeft(32, '2'),
                },
            },
        };
        if (withAudio)
        {
            var audioClipId = "91111111111111111111111111111111";
            tracks.Add(new VideoTimelineTrackDto
            {
                TrackId = audioTrackId,
                Kind = "audio",
                DisplayName = "Template audio",
                Clips =
                [
                    new VideoTimelineClipDto
                    {
                        ClipId = audioClipId, TrackId = audioTrackId, ClipKind = "audio",
                        TimelineStartTicks = 0, SourceStartTicks = 0, DurationTicks = 360_000,
                        MediaId = "3".PadLeft(32, '3'),
                    },
                ],
            });
            project.AudioTracks.Add(new VideoAudioTrackDto
            {
                TrackId = audioClipId, ClipId = audioClipId, LaneTrackId = audioTrackId,
                MediaId = "3".PadLeft(32, '3'), DurationTicks = 360_000, DurationMs = 4000,
                Volume = 1,
            });
        }
        return project;
    }

    private static VideoTimelineClipDto CreateTimelineClip(
        string id, string trackId, string eventId, string slotId, long startTicks) => new()
    {
        ClipId = id,
        TrackId = trackId,
        ClipKind = "image",
        TimelineStartTicks = startTicks,
        DurationTicks = 180_000,
        MediaId = slotId == "hero" ? "1".PadLeft(32, '1') : "2".PadLeft(32, '2'),
        TemplateMetadata = new Dictionary<string, object?>
        {
            ["eventId"] = eventId,
            ["slotId"] = slotId,
            ["templateId"] = "denim-story",
            ["templateDefinitionVersion"] = "1.0.0",
        },
        Properties = new Dictionary<string, object?> { ["fitMode"] = "cover", ["effect"] = "none" },
    };

    private static string? ReadString(object? value) => value switch
    {
        string text => text,
        JsonElement { ValueKind: JsonValueKind.String } element => element.GetString(),
        _ => null,
    };

    private sealed class FakeDraftPreviewService(VideoProjectDto project, TemporaryFiles files) : IVideoCreatorDraftPreviewService
    {
        private static readonly byte[] Png = Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pKsAAAAASUVORK5CYII=");
        public VideoProjectDto Project { get; private set; } = project;
        public List<VideoProjectDto> SavedProjects { get; } = [];
        public List<long> RenderedFrames { get; } = [];
        public Func<long, CancellationToken, Task>? BeforeFrame { get; set; }

        public Task<VideoProjectDto> GetProjectAsync(string projectId, CancellationToken cancellationToken = default) =>
            Task.FromResult(Project);

        public Task<IReadOnlyList<VideoProjectDto>> GetProjectsAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<VideoProjectDto>>([Project]);

        public Task<VideoProjectDto> SaveProjectAsync(VideoProjectDto updated, CancellationToken cancellationToken = default)
        {
            var saved = JsonSerializer.Deserialize<VideoProjectDto>(
                JsonSerializer.Serialize(updated, new JsonSerializerOptions(JsonSerializerDefaults.Web)),
                new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
            saved.Revision++;
            saved.UpdatedAt = DateTimeOffset.UtcNow;
            Project = saved;
            SavedProjects.Add(saved);
            return Task.FromResult(saved);
        }

        public async Task<VideoCompositionPreviewFrame> RenderFrameAsync(
            VideoProjectDto snapshot, long timestampTicks, CancellationToken cancellationToken = default)
        {
            RenderedFrames.Add(timestampTicks);
            if (BeforeFrame is not null) await BeforeFrame(timestampTicks, cancellationToken);
            return new VideoCompositionPreviewFrame(Png, 1, (int)(timestampTicks / 3000), "graph-fingerprint", "fake-renderer", snapshot.Revision);
        }

        public Task<string> RenderPlaybackPreviewAsync(VideoProjectDto snapshot, CancellationToken cancellationToken = default) =>
            Task.FromResult(files.WritePreview(snapshot.ProjectId, snapshot.Revision));
    }

    private sealed class TemporaryFiles : IDisposable
    {
        private readonly string _directory = Path.Combine(Path.GetTempPath(), "ms-test-" + Guid.NewGuid().ToString("N"));
        public string WritePreview(string projectId, int revision)
        {
            Directory.CreateDirectory(_directory);
            var path = Path.Combine(_directory, $"{projectId}-r{revision}-{Guid.NewGuid():N}.mp4");
            File.WriteAllBytes(path, [0, 0, 0, 24, 0x66, 0x74, 0x79, 0x70]);
            return path;
        }
        public void Dispose()
        {
            if (Directory.Exists(_directory)) Directory.Delete(_directory, recursive: true);
        }
    }
}
