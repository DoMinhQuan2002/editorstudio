using System.Net;
using System.Net.Http;
using System.IO;
using System.Text;
using System.Text.Json;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Tests;

public sealed class VideoCreatorGalleryViewModelTests
{
    [Fact]
    public async Task LoadsOnlyBackendTemplatesAndFiltersByCategoryAndSearch()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"denim","name":"Denim Story","description":"Fashion edit","category":"Story","durationMs":15000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":5,"requiredMediaSlots":5,"previewAvailable":false,"scenes":[]},
              {"templateId":"trip","name":"Travel Reel","description":"Journey","category":"Travel","durationMs":20000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":4,"requiredMediaSlots":4,"previewAvailable":false,"scenes":[]}
            ]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();

        Assert.Equal(2, viewModel.VisibleTemplates.Count);
        Assert.Null(viewModel.SelectedTemplate);
        Assert.False(viewModel.CanUseTemplate);
        Assert.Contains("Đã tải 2 mẫu", viewModel.CatalogStatus);
        Assert.Equal(new[] { "Tất cả", "Story", "Travel" }, viewModel.Categories.Select(item => item.Name));
        Assert.Equal("9:16", viewModel.VisibleTemplates[0].AspectRatio);
        Assert.Equal(5, viewModel.VisibleTemplates[0].RequiredMediaSlots);
        Assert.False(viewModel.VisibleTemplates[0].PreviewAvailable);
        Assert.Null(viewModel.VisibleTemplates[0].PosterPath);

        viewModel.SelectTemplateCommand.Execute(viewModel.VisibleTemplates[0]);
        Assert.Equal("denim", viewModel.SelectedTemplate?.TemplateId);
        Assert.True(viewModel.CanUseTemplate);
        Assert.True(viewModel.VisibleTemplates[0].IsSelected);

        viewModel.SearchText = "fashion";
        Assert.Equal("denim", viewModel.SelectedTemplate?.TemplateId);

        viewModel.SelectedCategory = "Travel";
        Assert.Empty(viewModel.VisibleTemplates);
        Assert.Null(viewModel.SelectedTemplate);
        Assert.False(viewModel.CanUseTemplate);

        viewModel.SearchText = "";
        Assert.Equal(new[] { "trip" }, viewModel.VisibleTemplates.Select(item => item.TemplateId));
        Assert.Null(viewModel.SelectedTemplate);

        viewModel.SelectedCategory = "Tất cả";
        viewModel.SearchText = "fashion";
        Assert.Equal(new[] { "denim" }, viewModel.VisibleTemplates.Select(item => item.TemplateId));
        Assert.Null(viewModel.SelectedTemplate);

        viewModel.SearchText = "missing";
        Assert.Empty(viewModel.VisibleTemplates);
        Assert.Equal("Không tìm thấy mẫu phù hợp", viewModel.EmptyStateTitle);
    }

    [Fact]
    public async Task DoesNotInventFallbackTemplatesWhenBackendIsUnavailable()
    {
        var viewModel = new VideoCreatorGalleryViewModel();
        await viewModel.LoadCatalogAsync();
        Assert.Empty(viewModel.VisibleTemplates);
        Assert.Null(viewModel.SelectedTemplate);
        Assert.Equal("Không thể tải mẫu video", viewModel.EmptyStateTitle);
        Assert.Contains("Backend chưa kết nối", viewModel.CatalogStatus);
    }

    [Fact]
    public async Task UsesCatalogMediaSlotCountWhenItDiffersFromSceneCount()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"custom","name":"Custom","description":"Slots differ","category":"Story","durationMs":12000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":3,"requiredMediaSlots":2,"previewAvailable":false,"scenes":[]}
            ]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();

        Assert.Equal(3, viewModel.VisibleTemplates[0].SceneCount);
        Assert.Equal(2, viewModel.VisibleTemplates[0].RequiredMediaSlots);
        viewModel.SelectTemplateCommand.Execute(viewModel.VisibleTemplates[0]);
        Assert.Contains("2 vị trí media", viewModel.SelectedTemplateSummary);
    }

    [Fact]
    public async Task PreviewBadgeReflectsCatalogAvailability()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"with-preview","name":"Preview","description":"Available","category":"Story","durationMs":12000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":1,"requiredMediaSlots":1,"previewAvailable":true,"previewSource":"preview.mp4","scenes":[]},
              {"templateId":"without-preview","name":"No preview","description":"Missing","category":"Story","durationMs":12000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":1,"requiredMediaSlots":1,"previewAvailable":false,"scenes":[]}
            ]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();

        Assert.Equal("Có preview", viewModel.VisibleTemplates[0].PreviewStatus);
        Assert.Equal("Chưa có preview", viewModel.VisibleTemplates[1].PreviewStatus);
    }

    [Fact]
    public async Task FallDiary03IsClearlyPilotAndOpensSelectionWithExactTemplateId()
    {
        var fall = new VideoTemplateDto
        {
            TemplateId = "fall-diary", Name = "Fall Diary", Description = "Reference pilot 0.3",
            Category = "Story", DurationMs = 17_000, Width = 1080, Height = 1920, AspectRatio = "9:16",
            SceneCount = 5, RequiredMediaSlots = 11, AvailabilityStatus = "PILOT_RENDERABLE",
            TemplateDefinitionVersion = "0.3.0-reference-pilot", PreviewAvailable = false,
            MediaSlotRequirements = Enumerable.Range(1, 11).Select(index => new VideoTemplateMediaSlotRequirementDto
            {
                SlotId = $"photo-{index:00}", AllowedMediaKinds = ["image"], Required = true,
                ReusePolicy = "allow", MissingSlotPolicy = "error"
            }).ToList(),
            Scenes = [new() { Name = "Opening", DurationMs = 5_767 }, new() { Name = "Autumn park", DurationMs = 4_000 },
                new() { Name = "Picnic", DurationMs = 3_500 }, new() { Name = "Food insert", DurationMs = 500 },
                new() { Name = "Bouquet", DurationMs = 3_233 }]
        };
        var json = System.Text.Json.JsonSerializer.Serialize(new { templates = new[] { fall } },
            new System.Text.Json.JsonSerializerOptions(System.Text.Json.JsonSerializerDefaults.Web));
        var client = CreateClient(json);
        var gallery = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client),
            new EmptyMediaService(), new EmptyPicker());

        await gallery.LoadCatalogAsync();
        var card = Assert.Single(gallery.VisibleTemplates);
        Assert.Equal("fall-diary", card.TemplateId);
        Assert.Equal(11, card.RequiredMediaSlots);
        Assert.Equal("Pilot · chưa có demo", card.PreviewStatus);
        gallery.OpenTemplateDetails(card.TemplateId);

        var details = Assert.IsType<VideoCreatorTemplateDetailsViewModel>(gallery.ActivePage);
        Assert.Equal("fall-diary", details.TemplateId);
        Assert.Equal("0.3.0-reference-pilot", details.Template!.TemplateDefinitionVersion);
        Assert.Equal("Pilot · chưa phát hành", details.AvailabilityStatusText);
        Assert.False(details.PreviewAvailable);
        Assert.Contains("ảnh", details.MediaRulesMessage);
        Assert.Contains("có thể dùng lại", details.MediaRulesMessage);
        await details.ChooseMediaCommand.ExecuteAsync();
        var session = Assert.IsType<MediaSelectionViewModel>(gallery.CurrentSelection);
        Assert.Equal("fall-diary", session.Request.TemplateId);
        Assert.Equal("0.3.0-reference-pilot", session.Template.TemplateDefinitionVersion);
        Assert.Equal(11, session.Slots.Count);
        Assert.DoesNotContain("0.0s", string.Join(" ", session.Slots.Select(slot => slot.Label)));

        session.BackCommand.Execute(null);
        await details.ChooseMediaCommand.ExecuteAsync();
        Assert.Same(session, gallery.CurrentSelection);
        Assert.Equal("fall-diary", gallery.CurrentSelection!.Request.TemplateId);
    }

    private sealed class EmptyPicker : IMediaFilePicker
    {
        public IReadOnlyList<string> PickMediaFiles() => [];
        public string? PickSaveVideoPath(string name) => null;
    }

    private sealed class EmptyMediaService : IMediaSelectionService
    {
        public Task<IReadOnlyList<VideoMediaDto>> ListAsync() => Task.FromResult<IReadOnlyList<VideoMediaDto>>([]);
        public Task<VideoMediaDto> ImportAsync(string path) => throw new NotImplementedException();
        public Task<byte[]> ThumbnailAsync(string id) => throw new NotImplementedException();
        public Task<string> PrepareAsync(string id, string version, Dictionary<string, string> bindings) =>
            Task.FromResult("{}");
    }

    [Fact]
    public async Task ReferenceOnlyTemplateShowsUnknownDurationAndAvailability()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"reference-only","name":"Reference only","description":"Unknown duration","category":"Story","durationMs":0,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":0,"requiredMediaSlots":0,"previewAvailable":false,"availabilityStatus":"REFERENCE_ONLY","scenes":[]}
            ]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();

        Assert.Equal("Unspecified", viewModel.VisibleTemplates[0].Duration);
        viewModel.SelectTemplateCommand.Execute(viewModel.VisibleTemplates[0]);
        viewModel.UseTemplateCommand.Execute(null);
        var details = Assert.IsType<VideoCreatorTemplateDetailsViewModel>(viewModel.ActivePage);
        Assert.Equal("REFERENCE_ONLY", details.AvailabilityStatus);
        Assert.Equal("Reference only", details.AvailabilityStatusText);
    }

    [Fact]
    public async Task GalleryDraftLabelRefreshesAfterSavedRevisionAdvances()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"fall-diary","name":"Fall Diary","description":"Reference pilot","category":"Story","durationMs":17000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":5,"requiredMediaSlots":11,"previewAvailable":false,"templateDefinitionVersion":"0.3.0-reference-pilot","availabilityStatus":"PILOT_RENDERABLE","scenes":[]}
            ]}
            """);
        var drafts = new MutableDraftPreviewService(CreateSavedDraft(2));
        var gallery = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client), draftPreviewService: drafts);

        await gallery.LoadCatalogAsync();

        Assert.Contains("r2", gallery.LatestSavedDraftLabel);
        drafts.Project = CreateSavedDraft(3);
        await gallery.RetryLoadCommand.ExecuteAsync();

        Assert.Contains("r3", gallery.LatestSavedDraftLabel);
        Assert.Contains("Fall Diary Reference Pilot 0.3", gallery.LatestSavedDraftLabel);
    }

    private static VideoProjectDto CreateSavedDraft(int revision) => new()
    {
        SchemaVersion = 2,
        ProjectId = "73da1503e49b403f9ad5c56f7d4d688c",
        TemplateId = "fall-diary",
        Title = "Fall Diary Reference Pilot 0.3",
        Revision = revision,
        UpdatedAt = DateTimeOffset.UtcNow,
        TemplateMetadata = new Dictionary<string, object?>
        {
            ["templateDefinitionVersion"] = JsonDocument.Parse("\"0.3.0-reference-pilot\"").RootElement.Clone(),
            ["templateBindings"] = JsonDocument.Parse("{\"photo-01\":\"asset-01\"}").RootElement.Clone(),
        },
    };

    private sealed class MutableDraftPreviewService(VideoProjectDto project) : IVideoCreatorDraftPreviewService
    {
        public VideoProjectDto Project { get; set; } = project;
        public Task<VideoProjectDto> GetProjectAsync(string projectId, CancellationToken cancellationToken = default) =>
            Task.FromResult(Project);
        public Task<IReadOnlyList<VideoProjectDto>> GetProjectsAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<VideoProjectDto>>([Project]);
        public Task<VideoProjectDto> SaveProjectAsync(VideoProjectDto project, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<VideoCompositionPreviewFrame> RenderFrameAsync(VideoProjectDto project, long timestampTicks, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<string> RenderPlaybackPreviewAsync(VideoProjectDto project, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }

    [Fact]
    public async Task OpensCatalogTemplateDetailsAndBackPreservesGalleryState()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"denim-story","name":"Denim Story","description":"Phong cách tối giản, hiện đại.","category":"Xu hướng","durationMs":15000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":5,"requiredMediaSlots":5,"previewAvailable":false,
               "scenes":[{"name":"Denim close-up","durationMs":3000},{"name":"Lookbook","durationMs":3000},{"name":"Fabric detail","durationMs":3000},{"name":"Everyday wear","durationMs":3000},{"name":"Final look","durationMs":3000}]}
            ]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();
        viewModel.SelectedCategory = "Xu hướng";
        viewModel.SearchText = "denim";
        viewModel.SelectTemplateCommand.Execute(viewModel.VisibleTemplates[0]);
        viewModel.UseTemplateCommand.Execute(null);

        var details = Assert.IsType<VideoCreatorTemplateDetailsViewModel>(viewModel.ActivePage);
        Assert.Equal("denim-story", details.TemplateId);
        Assert.Equal("Denim Story", details.Name);
        Assert.Equal("Phong cách tối giản, hiện đại.", details.Description);
        Assert.Equal("00:15", details.DurationText);
        Assert.Equal("9:16", details.AspectRatioText);
        Assert.Equal("1080 × 1920", details.ResolutionText);
        Assert.Equal(5, details.RequiredMediaSlots);
        Assert.Equal(5, details.Scenes.Count);
        Assert.Equal("3 giây", details.Scenes[0].DurationText);
        Assert.False(details.PreviewAvailable);
        Assert.False(details.HasPoster);
        Assert.Equal("Mẫu chưa có video xem trước", details.PreviewPlaceholderTitle);
        Assert.Equal("denim-story", details.MediaSelectionRequest.TemplateId);

        details.BackCommand.Execute(null);

        Assert.Same(viewModel, viewModel.ActivePage);
        Assert.Equal("Xu hướng", viewModel.SelectedCategory);
        Assert.Equal("denim", viewModel.SearchText);
        Assert.Equal("denim-story", viewModel.SelectedTemplate?.TemplateId);
    }

    [Fact]
    public async Task KeepsSceneDefinitionsSeparateFromMediaSlotCount()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"custom","name":"Custom","description":"Separate scene and slot counts","category":"Story","durationMs":12000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":3,"requiredMediaSlots":2,"previewAvailable":false,
               "scenes":[{"name":"One","durationMs":4000},{"name":"Two","durationMs":4000},{"name":"Three","durationMs":4000}]}
            ]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();
        viewModel.SelectTemplateCommand.Execute(viewModel.VisibleTemplates[0]);
        viewModel.OpenTemplateDetails("custom");

        var details = Assert.IsType<VideoCreatorTemplateDetailsViewModel>(viewModel.ActivePage);
        Assert.Equal(2, details.RequiredMediaSlots);
        Assert.Equal(3, details.Scenes.Count);
        Assert.Contains("mapping", details.SceneStructureMessage);
    }

    [Fact]
    public async Task DoesNotInferMediaSlotsFromScenesWhenCatalogOmitsSlotCount()
    {
        var client = CreateClient("""
            {"templates":[
              {"templateId":"unknown-slots","name":"Unknown slots","description":"No slot metadata","category":"Story","durationMs":12000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":3,"previewAvailable":false,
               "scenes":[{"name":"One","durationMs":4000},{"name":"Two","durationMs":4000},{"name":"Three","durationMs":4000}]}
            ]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();
        var card = viewModel.VisibleTemplates[0];
        Assert.Equal(3, card.SceneCount);
        Assert.Equal(0, card.RequiredMediaSlots);
        Assert.Equal("Chưa khai báo vị trí media", card.RequiredMediaSlotsText);
        viewModel.OpenTemplateDetails(card.TemplateId);

        var details = Assert.IsType<VideoCreatorTemplateDetailsViewModel>(viewModel.ActivePage);
        Assert.Equal("Số vị trí media chưa được cung cấp", details.RequiredMediaSlotsText);
    }

    [Fact]
    public async Task InvalidTemplateIdShowsErrorAndDoesNotRouteToEditor()
    {
        var client = CreateClient("""
            {"templates":[{"templateId":"known","name":"Known","description":"","category":"Story","durationMs":5000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":0,"requiredMediaSlots":0,"previewAvailable":false,"scenes":[]}]}
            """);
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));
        await viewModel.LoadCatalogAsync();

        viewModel.OpenTemplateDetails("missing-id");

        var details = Assert.IsType<VideoCreatorTemplateDetailsViewModel>(viewModel.ActivePage);
        Assert.True(details.IsError);
        Assert.Contains("missing-id", details.ErrorMessage);
        Assert.True(details.RetryCommand.CanExecute(null));
    }

    [Fact]
    public async Task GalleryRetryReloadsCatalogAfterBackendFailure()
    {
        var handler = new SequenceResponseHandler(
            new HttpResponseMessage(HttpStatusCode.ServiceUnavailable),
            new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""
                    {"templates":[{"templateId":"denim-story","name":"Denim Story","description":"Fashion","category":"Xu hướng","durationMs":15000,"width":1080,"height":1920,"aspectRatio":"9:16","sceneCount":5,"requiredMediaSlots":5,"previewAvailable":false,"scenes":[]}]}
                    """, Encoding.UTF8, "application/json")
            });
        var client = new MediaStudioApiClient(new HttpClient(handler) { BaseAddress = new Uri("http://localhost/") });
        var viewModel = new VideoCreatorGalleryViewModel(new TemplateCatalogService(client));

        await viewModel.LoadCatalogAsync();
        Assert.True(viewModel.IsCatalogLoadFailed);
        Assert.Empty(viewModel.VisibleTemplates);

        await viewModel.RetryLoadCommand.ExecuteAsync();

        Assert.False(viewModel.IsCatalogLoadFailed);
        Assert.Equal("denim-story", viewModel.VisibleTemplates.Single().TemplateId);
    }

    [Fact]
    public void PreviewRequiresAValidExistingLocalVideoAsset()
    {
        var backCalled = false;
        var remote = new VideoCreatorTemplateDetailsViewModel(new VideoTemplateDto
        {
            TemplateId = "remote-preview",
            Name = "Remote preview",
            PreviewAvailable = true,
            PreviewSource = "https://example.invalid/preview.mp4"
        }, () => backCalled = true);

        Assert.False(remote.PreviewAvailable);
        Assert.Contains("endpoint", remote.PreviewMessage);

        var temporaryVideo = Path.Combine(Path.GetTempPath(), $"mediastudio-preview-{Guid.NewGuid():N}.mp4");
        try
        {
            File.WriteAllBytes(temporaryVideo, [0, 0, 0, 0]);
            var local = new VideoCreatorTemplateDetailsViewModel(new VideoTemplateDto
            {
                TemplateId = "local-preview",
                Name = "Local preview",
                PreviewAvailable = true,
                PreviewSource = temporaryVideo
            }, () => backCalled = true);

            Assert.True(local.PreviewAvailable);
            Assert.True(local.PreviewUri?.IsFile);
            local.BackCommand.Execute(null);
            Assert.True(backCalled);
        }
        finally
        {
            File.Delete(temporaryVideo);
        }
    }

    private static MediaStudioApiClient CreateClient(string json) =>
        new(new HttpClient(new ResponseHandler(json)) { BaseAddress = new Uri("http://localhost/") });

    private sealed class ResponseHandler(string body) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json")
            });
    }

    private sealed class SequenceResponseHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private int _index;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var response = responses[Math.Min(_index, responses.Length - 1)];
            _index++;
            return Task.FromResult(response);
        }
    }
}
