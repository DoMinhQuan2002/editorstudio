using System.Windows;
using System.Windows.Controls;

namespace MediaStudio.Desktop.Views;

/// <summary>Sizes its child to <see cref="HeightPerWidth"/> × the available width.</summary>
public sealed class AspectFrame : Decorator
{
    public static readonly DependencyProperty HeightPerWidthProperty = DependencyProperty.Register(
        nameof(HeightPerWidth), typeof(double), typeof(AspectFrame),
        new FrameworkPropertyMetadata(16d / 9d, FrameworkPropertyMetadataOptions.AffectsMeasure));

    public double HeightPerWidth
    {
        get => (double)GetValue(HeightPerWidthProperty);
        set => SetValue(HeightPerWidthProperty, value);
    }

    protected override Size MeasureOverride(Size constraint)
    {
        var width = double.IsInfinity(constraint.Width) ? 220 : Math.Max(0, constraint.Width);
        var height = width * HeightPerWidth;
        Child?.Measure(new Size(width, height));
        return new Size(width, height);
    }

    protected override Size ArrangeOverride(Size arrangeSize)
    {
        var height = arrangeSize.Width * HeightPerWidth;
        Child?.Arrange(new Rect(0, 0, arrangeSize.Width, height));
        return new Size(arrangeSize.Width, height);
    }
}
