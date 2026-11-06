using System.Windows;
using System.Windows.Controls;

namespace MediaStudio.Desktop.Views;

/// <summary>Sizes its child to a true 9:16 portrait frame from the available card width.</summary>
public sealed class PortraitAspectFrame : Decorator
{
    private const double HeightPerWidth = 16d / 9d;

    public static double GetHeightForWidth(double width) => Math.Max(0, width) * HeightPerWidth;

    protected override Size MeasureOverride(Size constraint)
    {
        var width = constraint.Width;
        if (double.IsInfinity(width))
        {
            var desiredWidth = Child?.DesiredSize.Width ?? 0;
            width = desiredWidth > 0 ? desiredWidth : 180;
        }
        width = Math.Max(0, width);
        var height = GetHeightForWidth(width);
        Child?.Measure(new Size(width, height));
        return new Size(width, height);
    }

    protected override Size ArrangeOverride(Size arrangeSize)
    {
        var height = GetHeightForWidth(arrangeSize.Width);
        Child?.Arrange(new Rect(0, 0, arrangeSize.Width, height));
        return new Size(arrangeSize.Width, height);
    }
}
