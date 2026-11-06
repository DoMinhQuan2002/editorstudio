using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows;
using System.Windows.Media;

namespace MediaStudio.Desktop.Views;

public partial class UpscaleToolView : UserControl
{
    private double _comparisonFraction = 0.5;

    public UpscaleToolView() => InitializeComponent();

    private void ComparisonSurface_OnSizeChanged(object sender, SizeChangedEventArgs e)
    {
        UpdateComparisonOverlay();
    }

    private void ComparisonHandle_OnDragDelta(object sender, DragDeltaEventArgs e)
    {
        if (ComparisonSurface.ActualWidth <= 0) return;
        _comparisonFraction = Math.Clamp(_comparisonFraction + e.HorizontalChange / ComparisonSurface.ActualWidth, 0.03, 0.97);
        UpdateComparisonOverlay();
    }

    private void UpdateComparisonOverlay()
    {
        var width = ComparisonSurface.ActualWidth;
        var height = ComparisonSurface.ActualHeight;
        if (width <= 0 || height <= 0) return;

        var split = width * _comparisonFraction;
        ResultPreviewClip.Clip = new RectangleGeometry(new Rect(split, 0, width - split, height));
        BeforeTint.Clip = new RectangleGeometry(new Rect(0, 0, split, height));
        ComparisonDivider.Margin = new Thickness(Math.Max(0, split - ComparisonDivider.Width / 2), 0, 0, 0);
        ComparisonHandle.Margin = new Thickness(Math.Clamp(split - ComparisonHandle.ActualWidth / 2, 0, width - ComparisonHandle.ActualWidth), 0, 0, 0);
    }
}
