using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;
using MediaStudio.Desktop.Views;
using System.Reflection;

namespace MediaStudio.Desktop.Tests;

public sealed class SourceCoordinateAndViewModelTests
{
    [Fact]
    public void FitLetterboxAndNonsquareImageMapBackToSourcePixels()
    {
        var transform = new SourceImageTransform(1200, 800, 900, 700);
        Assert.Equal(0.75, transform.Scale, 8);
        Assert.Equal(50, transform.ImageTop, 8);

        var view = transform.SourceToView(437.5, 281.5);
        Assert.True(transform.TryViewToSource(view.X, view.Y, out SourceImagePoint source));
        Assert.Equal(new SourceImagePoint(437, 281), source);
        Assert.False(transform.TryViewToSource(450, 20, out SourceImagePoint _));
    }

    [Fact]
    public void ZoomAndPanInverseMappingPreservesSourceMark()
    {
        var transform = new SourceImageTransform(4432, 4432, 1013, 687, 2.0, 37, -22);
        var expectedX = 2410.4;
        var expectedY = 1495.8;
        var view = transform.SourceToView(expectedX, expectedY);
        Assert.True(transform.TryViewToSource(view.X, view.Y, out double actualX, out double actualY));
        Assert.Equal(expectedX, actualX, 8);
        Assert.Equal(expectedY, actualY, 8);
        Assert.Equal(170, transform.ViewRadiusToSource(170 * transform.Scale), 8);
    }

    [Fact]
    public void DpiLayoutResizeOnlyChangesViewTransformNotStoredSourcePoint()
    {
        var point = new SourceImagePoint(301, 187);
        var normalDpi = new SourceImageTransform(554, 554, 800, 600, 1.0);
        var scaledDpiLayout = new SourceImageTransform(554, 554, 1200, 900, 1.0);
        var normalView = normalDpi.SourceToView(point.X + 0.5, point.Y + 0.5);
        var scaledView = scaledDpiLayout.SourceToView(point.X + 0.5, point.Y + 0.5);

        Assert.True(normalDpi.TryViewToSource(normalView.X, normalView.Y, out var normalSource));
        Assert.True(scaledDpiLayout.TryViewToSource(scaledView.X, scaledView.Y, out var scaledSource));
        Assert.Equal(point, normalSource);
        Assert.Equal(point, scaledSource);
    }

    [Theory]
    [InlineData(1.0)]
    [InlineData(1.25)]
    public void PhysicalMouseCoordinatesRoundTripThroughWpfDipAtSupportedDpi(double dpiScale)
    {
        var transform = new SourceImageTransform(1200, 800, 900, 700, 1.35, -12, 18);
        var expectedX = 743.25;
        var expectedY = 392.75;
        var viewDip = transform.SourceToView(expectedX, expectedY);
        var screenOriginDevice = (X: 411.0, Y: 173.0);
        var physicalMouse = (X: screenOriginDevice.X + viewDip.X * dpiScale,
                             Y: screenOriginDevice.Y + viewDip.Y * dpiScale);
        var wpfPositionDip = ((physicalMouse.X - screenOriginDevice.X) / dpiScale,
                              (physicalMouse.Y - screenOriginDevice.Y) / dpiScale);

        Assert.True(transform.TryViewToSource(wpfPositionDip.Item1, wpfPositionDip.Item2,
            out double actualX, out double actualY));
        Assert.Equal(expectedX, actualX, 8);
        Assert.Equal(expectedY, actualY, 8);
    }

    [Fact]
    public void PixelBoundaryAndHorizontalEdgeUseContinuousSourceCoordinatesThenFloorForPixelIndex()
    {
        var transform = new SourceImageTransform(100, 80, 100, 80);

        Assert.True(transform.TryViewToSource(12.0, 20.0, out SourceImagePoint onBoundary));
        Assert.Equal(new SourceImagePoint(12, 20), onBoundary);
        Assert.True(transform.TryViewToSource(12.5, 20.5, out SourceImagePoint insidePixel));
        Assert.Equal(new SourceImagePoint(12, 20), insidePixel);
        Assert.False(transform.TryViewToSource(100.0, 20.0, out SourceImagePoint _));
        Assert.False(transform.TryViewToSource(12.0, 80.0, out SourceImagePoint _));
    }

    [Fact]
    public void ViewModelRequiresBackendAndCanEditGuidanceBeforeAnalysis()
    {
        var viewModel = new ForegroundProtectionLabViewModel(new NoOpImagePicker(), api: null);
        Assert.False(viewModel.AnalyzeCommand.CanExecute(null));
        Assert.False(viewModel.CanProtect);

        Assert.True(viewModel.AddPolygonRoi([
            new SourceImageCoordinate(280, 166),
            new SourceImageCoordinate(322, 166),
            new SourceImageCoordinate(322, 208),
            new SourceImageCoordinate(280, 208)
        ]));
        viewModel.AddForegroundSeed(new SourceImagePoint(301, 187));
        viewModel.AddBackgroundSeed(new SourceImagePoint(280, 180));

        Assert.True(viewModel.HasRoi);
        Assert.Equal(1, viewModel.ForegroundSeedCount);
        Assert.Equal(1, viewModel.BackgroundSeedCount);
        Assert.False(viewModel.AnalyzeCommand.CanExecute(null));

        viewModel.RemoveLastBackgroundSeedCommand.Execute(null);
        Assert.Equal(0, viewModel.BackgroundSeedCount);
        viewModel.ClearMarksCommand.Execute(null);
        Assert.False(viewModel.HasRoi);
        Assert.Equal(0, viewModel.ForegroundSeedCount);
        Assert.False(viewModel.CanAnalyze);
    }

    [Fact]
    public void CanRedoBindingRefreshesWhenBusyStateChanges()
    {
        var viewModel = new ForegroundProtectionLabViewModel(new NoOpImagePicker(), api: null);
        typeof(ForegroundProtectionLabViewModel)
            .GetField("_sessionId", BindingFlags.Instance | BindingFlags.NonPublic)!
            .SetValue(viewModel, "session");
        typeof(ForegroundProtectionLabViewModel)
            .GetField("_canRedo", BindingFlags.Instance | BindingFlags.NonPublic)!
            .SetValue(viewModel, true);

        var changedProperties = new List<string?>();
        viewModel.PropertyChanged += (_, args) => changedProperties.Add(args.PropertyName);
        var isBusySetter = typeof(ForegroundProtectionLabViewModel)
            .GetProperty(nameof(ForegroundProtectionLabViewModel.IsBusy))!
            .GetSetMethod(nonPublic: true)!;

        isBusySetter.Invoke(viewModel, [true]);
        Assert.False(viewModel.CanRedo);
        Assert.False(viewModel.RedoCommand.CanExecute(null));

        changedProperties.Clear();
        isBusySetter.Invoke(viewModel, [false]);

        Assert.True(viewModel.CanRedo);
        Assert.True(viewModel.RedoCommand.CanExecute(null));
        Assert.Contains(nameof(ForegroundProtectionLabViewModel.CanRedo), changedProperties);
    }

    private sealed class NoOpImagePicker : IImagePicker
    {
        public string? PickImage() => null;
        public string? PickSavePath(string defaultFileName, string format) => null;
    }
}
