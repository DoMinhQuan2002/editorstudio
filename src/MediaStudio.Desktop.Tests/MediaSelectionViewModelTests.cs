using System.IO;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;
using System.Net;
using System.Net.Http;

namespace MediaStudio.Desktop.Tests;

public sealed class MediaSelectionViewModelTests
{
    private static VideoTemplateDto Template() => new()
    {
        TemplateId = "exact-id", Name = "Different name", AvailabilityStatus = "PILOT_RENDERABLE",
        TemplateDefinitionVersion = "1.0.0-legacy",
        MediaSlotRequirements = [new() { SlotId = "hero", AllowedMediaKinds = ["image", "video"], Required = true, DurationMs = 3000 },
                                 new() { SlotId = "detail", AllowedMediaKinds = ["image"], Required = true }]
    };

    private static VideoTemplateDto FallDiaryTemplate() => new()
    {
        TemplateId = "fall-diary", Name = "Fall Diary", AvailabilityStatus = "PILOT_RENDERABLE",
        TemplateDefinitionVersion = "0.8.0-intro-title", RequiredMediaSlots = 1,
        MediaSlotRequirements = Enumerable.Range(0, 36).Select(index =>
        {
            var group = index / 9 + 1;
            var position = index % 9;
            return new VideoTemplateMediaSlotRequirementDto
            {
                SlotId = position == 0 ? $"group-{group:00}-background" : $"group-{group:00}-overlay-{position:00}",
                AllowedMediaKinds = position == 0 ? ["image", "video"] : ["image"],
                Required = index == 0,
                ReusePolicy = "allow",
                MissingSlotPolicy = index == 0 ? "error" : "skip_event",
            };
        }).ToList(),
    };
    [Fact]
    public async Task SelectionOrderReplaceDeselectAndPayloadUseExactIds()
    {
        var service = new FakeService();
        var vm = new MediaSelectionViewModel(Template(), new("exact-id"), service, new Picker(), () => { });
        await vm.LoadAsync();
        var image = vm.Media.Single(i => i.Media.Kind == "image");
        var video = vm.Media.Single(i => i.Media.Kind == "video");
        vm.Toggle(image); vm.Toggle(video);
        Assert.Equal(1, image.Order); Assert.Equal(2, video.Order);
        Assert.False(vm.PrepareCommand.CanExecute(null));
        Assert.True(vm.Assign(vm.Slots[0], video));
        Assert.False(vm.Assign(vm.Slots[1], video));
        Assert.True(vm.Assign(vm.Slots[1], image));
        await vm.PrepareCommand.ExecuteAsync();
        Assert.Equal("exact-id", service.Id);
        Assert.Equal(video.Media.AssetId, service.Bindings!["hero"]);
        Assert.NotNull(vm.PreparedPayload);
        Assert.True(vm.Assign(vm.Slots[0], image));
        Assert.Null(vm.PreparedPayload);
        vm.RemoveBindingCommand.Execute(vm.Slots[0]);
        Assert.Null(vm.Slots[0].Media);
        Assert.Same(image, vm.Slots[1].Media);
        Assert.False(vm.PrepareCommand.CanExecute(null));
        Assert.True(vm.Assign(vm.Slots[0], video));
        vm.Toggle(image);
        Assert.Null(vm.Slots[1].Media);
        Assert.Same(video, vm.Slots[0].Media);
        Assert.Equal(1, video.Order);
        Assert.False(vm.PrepareCommand.CanExecute(null));
    }
    [Fact]
    public async Task RepeatedLoadPreservesSessionAndRejectsShortVideo()
    {
        var vm = new MediaSelectionViewModel(Template(), new("exact-id"), new FakeService(), new Picker(), () => { });
        await vm.LoadAsync(); var item = vm.Media.First(); vm.Toggle(item); await vm.LoadAsync();
        Assert.Same(item, vm.Selected.Single()); Assert.Single(vm.Media);
        var video = vm.Selected.Single(i => i.Media.Kind == "video"); video.Media.DurationMs = 100;
        if (!vm.Selected.Contains(video)) vm.Toggle(video);
        Assert.False(vm.Assign(vm.Slots[0], video));
    }

    [Fact]
    public async Task FallDiaryAutoAssignsPartialGroupsAndRejectsVideoInOverlayPositions()
    {
        var vm = new MediaSelectionViewModel(FallDiaryTemplate(), new("fall-diary"),
            new DynamicFakeService(videoIndex: 7), new Picker(), () => { });
        await vm.LoadAsync();
        var video = vm.Media.Single(item => item.Media.FileName == "media-7");
        vm.Toggle(vm.Media.Single(item => item.Media.FileName == "media-0"));
        vm.Toggle(vm.Media.Single(item => item.Media.FileName == "media-1"));
        Assert.DoesNotContain(video, vm.Media);
        vm.Toggle(video);
        vm.Toggle(vm.Media.Single(item => item.Media.FileName == "media-2"));

        Assert.Equal(4, vm.Slots.Count);
        Assert.Equal(3, vm.BuildBindings().Count);
        Assert.Equal("1. Nền nhóm 1", vm.Slots[0].Label);
        Assert.Null(vm.Slots[2].Media);
        Assert.Contains("chỉ nhận ảnh", vm.Status);
        Assert.False(vm.PrepareCommand.CanExecute(null));

        vm.Toggle(video);
        Assert.Equal(3, vm.Slots.Count);
        Assert.Equal(3, vm.BuildBindings().Count);
        Assert.Same(vm.Selected[2], vm.Slots[2].Media);
        Assert.True(vm.PrepareCommand.CanExecute(null));
    }

    [Fact]
    public async Task FallDiaryAllowsVideoAtEveryNinthItemAndStopsAtThirtySix()
    {
        var vm = new MediaSelectionViewModel(FallDiaryTemplate(), new("fall-diary"),
            new DynamicFakeService(videoIndex: 9), new Picker(), () => { });
        await vm.LoadAsync();
        for (var index = 0; index < 10; index++)
            vm.Toggle(vm.Media.Single(item => item.Media.FileName == $"media-{index}"));
        Assert.Equal(10, vm.Slots.Count);
        Assert.Equal("10. Nền nhóm 2", vm.Slots[9].Label);
        Assert.Equal("video", vm.Slots[9].Media!.Media.Kind);
        Assert.Equal(10, vm.BuildBindings().Count);

        var capped = new MediaSelectionViewModel(FallDiaryTemplate(), new("fall-diary"),
            new DynamicFakeService(videoIndex: -1), new Picker(), () => { });
        await capped.LoadAsync();
        foreach (var item in capped.Media.Where(item => item.Media.FileName.StartsWith("media-", StringComparison.Ordinal))
                     .OrderBy(item => int.Parse(item.Media.FileName.AsSpan("media-".Length))))
            capped.Toggle(item);
        Assert.Equal(36, capped.Selected.Count);
        Assert.Equal(36, capped.Slots.Count);
        Assert.Contains("tối đa 36", capped.Status, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task FallDiaryFirstVideoBackgroundMustCoverFivePointTwoSeconds()
    {
        var vm = new MediaSelectionViewModel(FallDiaryTemplate(), new("fall-diary"),
            new DynamicFakeService(videoIndex: 0), new Picker(), () => { });
        await vm.LoadAsync();
        vm.Toggle(vm.Media.Single(item => item.Media.FileName == "media-0"));

        Assert.Null(vm.Slots[0].Media);
        Assert.False(vm.PrepareCommand.CanExecute(null));
        Assert.Contains("giây", vm.Status);
    }

    [Fact]
    public void ReferenceOnlyAndMissingDefinitionsCannotOpen()
    {
        var template = Template(); template.AvailabilityStatus = "REFERENCE_ONLY";
        Assert.False(MediaSelectionViewModel.IsEligible(template));
        Assert.Throws<ArgumentException>(() => new MediaSelectionViewModel(template, new("exact-id"), new FakeService(), new Picker(), () => { }));
        template = Template(); template.MediaSlotRequirements.Clear();
        Assert.False(MediaSelectionViewModel.IsEligible(template));
        Assert.Throws<ArgumentException>(() => new MediaSelectionViewModel(Template(), new("Different name"), new FakeService(), new Picker(), () => { }));
    }
    [Fact]
    public async Task GalleryDetailsSelectionBackAndReentryRetainTheExactTemplateSession()
    {
        var first = Template(); first.MediaSlotRequirements.RemoveAt(1);
        var second = Template(); second.TemplateId = "other-id"; second.MediaSlotRequirements.Clear();
        second.MediaSlotRequirements.Add(new() { SlotId = "only-slot", AllowedMediaKinds = ["image"], Required = true });
        var json = System.Text.Json.JsonSerializer.Serialize(new { templates = new[] { first, second } },
            new System.Text.Json.JsonSerializerOptions(System.Text.Json.JsonSerializerDefaults.Web));
        var http = new HttpClient(new CatalogHandler(json)) { BaseAddress = new Uri("http://localhost/") };
        var service = new FakeService();
        var gallery = new VideoCreatorGalleryViewModel(new TemplateCatalogService(new MediaStudioApiClient(http)), service, new Picker());
        await gallery.LoadCatalogAsync();
        gallery.OpenTemplateDetails("exact-id");
        var details = gallery.CurrentDetails!;
        await details.ChooseMediaCommand.ExecuteAsync();
        var firstSession = gallery.CurrentSelection!;
        var chosen = firstSession.Media.Single(i => i.Media.Kind == "image"); firstSession.Toggle(chosen);
        firstSession.BackCommand.Execute(null);
        Assert.Null(gallery.CurrentSelection);
        await details.ChooseMediaCommand.ExecuteAsync();
        Assert.Same(firstSession, gallery.CurrentSelection);
        Assert.Same(chosen, gallery.CurrentSelection!.Selected.Single());
        gallery.OpenTemplateDetails("other-id");
        await gallery.CurrentDetails!.ChooseMediaCommand.ExecuteAsync();
        Assert.NotSame(firstSession, gallery.CurrentSelection);
        Assert.Equal("other-id", gallery.CurrentSelection!.Request.TemplateId);
        Assert.Single(gallery.CurrentSelection.Slots);
        gallery.OpenTemplateDetails("exact-id");
        await gallery.CurrentDetails!.ChooseMediaCommand.ExecuteAsync();
        Assert.Same(firstSession, gallery.CurrentSelection);
        Assert.Same(chosen, gallery.CurrentSelection!.Selected.Single());
    }
    [Theory]
    [InlineData("image", "video")]
    [InlineData("video", "image")]
    public async Task LibraryTypeFilterIntersectsNextSlotAndRefreshesAfterRemoval(string allowed, string excluded)
    {
        var template = Template();
        template.MediaSlotRequirements[1].AllowedMediaKinds = [allowed];
        var vm = new MediaSelectionViewModel(template, new("exact-id"), new FakeService(), new Picker(), () => { });
        await vm.LoadAsync();
        var first = vm.Media.Single(item => item.Media.Kind == excluded);
        vm.Toggle(first);
        Assert.All(vm.Media, item => Assert.Equal(allowed, item.Media.Kind));
        vm.FilterCommand.Execute(excluded);
        Assert.Empty(vm.Media);
        Assert.True(vm.IsLibraryEmpty);
        vm.Toggle(first);
        Assert.Single(vm.Media);
        Assert.Equal(excluded, vm.Media[0].Media.Kind);
        vm.FilterCommand.Execute("all");
        Assert.Equal(2, vm.Media.Count);
    }

    [Fact]
    public async Task DynamicLibraryRestoresVideosAtNextBackground()
    {
        var vm = new MediaSelectionViewModel(FallDiaryTemplate(), new("fall-diary"),
            new DynamicFakeService(videoIndex: 9), new Picker(), () => { });
        await vm.LoadAsync();
        vm.Toggle(vm.Media.Single(item => item.Media.FileName == "media-0"));
        vm.FilterCommand.Execute("video");
        Assert.Empty(vm.Media);
        vm.FilterCommand.Execute("image");
        for (var index = 1; index < 9; index++)
            vm.Toggle(vm.Media.Single(item => item.Media.FileName == $"media-{index}"));
        vm.FilterCommand.Execute("video");
        Assert.Single(vm.Media);
    }

    [Fact]
    public async Task BulkMarksAreSeparateFromTemplateAndDeletePersistsAfterReload()
    {
        var service = new FakeService();
        var template = Template(); template.MediaSlotRequirements[1].AllowedMediaKinds = ["image", "video"];
        var vm = new MediaSelectionViewModel(template, new("exact-id"), service, new Picker(), () => { });
        await vm.LoadAsync();
        var first = vm.Media[0]; var last = vm.Media[1];
        vm.MarkLibraryItem(first, false, false);
        vm.MarkLibraryItem(last, true, false);
        Assert.Equal(2, vm.MarkedMediaCount);
        Assert.Empty(vm.Selected);
        vm.Toggle(first);
        await vm.DeleteLibraryCommand.ExecuteAsync();
        Assert.Empty(vm.Media); Assert.Empty(vm.Selected);
        Assert.All(vm.Slots, slot => Assert.Null(slot.Media));
        await vm.LoadAsync();
        Assert.Empty(vm.Media);
    }

    [Fact]
    public async Task PlusAddsToTemplateWhileCardClickOnlyMarksForDeletion()
    {
        var service = new FakeService();
        var vm = new MediaSelectionViewModel(Template(), new("exact-id"), service, new Picker(), () => { });
        await vm.LoadAsync();
        var image = vm.Media.Single(item => item.Media.Kind == "image");
        vm.MarkLibraryItem(image, extend: false, toggle: false);
        Assert.Empty(vm.Selected);
        Assert.Equal(1, vm.MarkedMediaCount);
        vm.AddToSelectionCommand.Execute(image);
        Assert.Same(image, vm.Selected.Single());
        Assert.Equal(1, vm.MarkedMediaCount);
        Assert.False(vm.AddToSelectionCommand.CanExecute(image));
    }

    [Fact]
    public async Task FailedDeletionRetainsSelectionAndFilterExcludesHiddenMarks()
    {
        var service = new FakeService { FailDelete = true };
        var vm = new MediaSelectionViewModel(Template(), new("exact-id"), service, new Picker(), () => { });
        await vm.LoadAsync();
        vm.MarkAllLibraryCommand.Execute(null);
        vm.FilterCommand.Execute("image");
        Assert.Equal(1, vm.MarkedMediaCount);
        await vm.DeleteLibraryCommand.ExecuteAsync();
        Assert.Single(vm.Media); Assert.Equal(1, vm.MarkedMediaCount);
        Assert.Contains("Không xóa", vm.Status);
        vm.IsBulkSelecting = false;
        Assert.Equal(0, vm.MarkedMediaCount);
    }

    private sealed class Picker : IMediaFilePicker
    {
        public IReadOnlyList<string> PickMediaFiles() => [];
        public string? PickSaveVideoPath(string name) => null;
    }
    private sealed class CatalogHandler(string json) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json) });
    }
    private sealed class FakeService : IMediaSelectionService
    {
        private readonly HashSet<string> _deleted = [];
        public bool FailDelete;
        public Task DeleteFromLibraryAsync(IReadOnlyList<string> ids)
        {
            if (FailDelete) throw new IOException("Server unavailable");
            _deleted.UnionWith(ids);
            return Task.CompletedTask;
        }
        public string? Id;
        public Dictionary<string, string>? Bindings;
        public Task<IReadOnlyList<VideoMediaDto>> ListAsync() => Task.FromResult<IReadOnlyList<VideoMediaDto>>(new VideoMediaDto[] {
            new() { AssetId = new('a', 32), Kind = "image", Width = 100, Height = 100 },
            new() { AssetId = new('b', 32), Kind = "video", VideoCodec = "h264", DurationMs = 5000 }}.Where(item => !_deleted.Contains(item.AssetId)).ToArray());
        public Task<VideoMediaDto> ImportAsync(string path) => throw new NotImplementedException();
        public Task<byte[]> ThumbnailAsync(string id) => throw new NotImplementedException();
        public Task<string> PrepareAsync(string id, string version, Dictionary<string, string> bindings)
        { Id = id; Bindings = bindings; return Task.FromResult("{\"bindings\":{}}"); }
    }

    private sealed class DynamicFakeService(int videoIndex) : IMediaSelectionService
    {
        public Task<IReadOnlyList<VideoMediaDto>> ListAsync() => Task.FromResult<IReadOnlyList<VideoMediaDto>>(
            Enumerable.Range(0, 37).Select(index => new VideoMediaDto
            {
                AssetId = index.ToString("x32"),
                FileName = $"media-{index}",
                Kind = index == videoIndex ? "video" : "image",
                Width = 100,
                Height = 100,
                DurationMs = index == videoIndex ? 5_000 : null,
                VideoCodec = index == videoIndex ? "h264" : null,
            }).ToList());
        public Task<VideoMediaDto> ImportAsync(string path) => throw new NotImplementedException();
        public Task<byte[]> ThumbnailAsync(string id) => throw new NotImplementedException();
        public Task<string> PrepareAsync(string id, string version, Dictionary<string, string> bindings) =>
            Task.FromResult("{\"bindings\":{}}");
    }
}
