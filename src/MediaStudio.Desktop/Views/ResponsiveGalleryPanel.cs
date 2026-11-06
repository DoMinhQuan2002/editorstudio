using System.Windows;
using System.Windows.Controls;

namespace MediaStudio.Desktop.Views;

/// <summary>Arranges a small template catalog into responsive equal-width columns.</summary>
public sealed class ResponsiveGalleryPanel : Panel
{
    public static readonly DependencyProperty MinItemWidthProperty = DependencyProperty.Register(
        nameof(MinItemWidth), typeof(double), typeof(ResponsiveGalleryPanel),
        new FrameworkPropertyMetadata(220d, FrameworkPropertyMetadataOptions.AffectsMeasure));

    public static readonly DependencyProperty ItemSpacingProperty = DependencyProperty.Register(
        nameof(ItemSpacing), typeof(double), typeof(ResponsiveGalleryPanel),
        new FrameworkPropertyMetadata(16d, FrameworkPropertyMetadataOptions.AffectsMeasure));

    public static readonly DependencyProperty MaxColumnsProperty = DependencyProperty.Register(
        nameof(MaxColumns), typeof(int), typeof(ResponsiveGalleryPanel),
        new FrameworkPropertyMetadata(6, FrameworkPropertyMetadataOptions.AffectsMeasure));

    public double MinItemWidth
    {
        get => (double)GetValue(MinItemWidthProperty);
        set => SetValue(MinItemWidthProperty, value);
    }

    public double ItemSpacing
    {
        get => (double)GetValue(ItemSpacingProperty);
        set => SetValue(ItemSpacingProperty, value);
    }

    public int MaxColumns
    {
        get => (int)GetValue(MaxColumnsProperty);
        set => SetValue(MaxColumnsProperty, value);
    }

    private int _columns = 1;
    private double _itemWidth;

    public static int GetColumnCount(double availableWidth, double minItemWidth, double spacing, int maxColumns, int itemCount)
    {
        if (itemCount <= 0) return 1;
        var safeSpacing = Math.Max(0, spacing);
        var safeMinimumWidth = Math.Max(1, minItemWidth);
        var possibleColumns = (int)Math.Floor((Math.Max(0, availableWidth) + safeSpacing) / (safeMinimumWidth + safeSpacing));
        return Math.Clamp(possibleColumns, 1, Math.Max(1, maxColumns));
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        if (InternalChildren.Count == 0)
        {
            _columns = 1;
            _itemWidth = 0;
            return new Size(0, 0);
        }

        var spacing = Math.Max(0, ItemSpacing);
        var minimumWidth = Math.Max(1, MinItemWidth);
        var availableWidth = double.IsInfinity(availableSize.Width)
            ? minimumWidth * Math.Max(1, MaxColumns) + spacing * (Math.Max(1, MaxColumns) - 1)
            : Math.Max(0, availableSize.Width);
        _columns = GetColumnCount(availableWidth, minimumWidth, spacing, MaxColumns, InternalChildren.Count);
        _itemWidth = Math.Max(0, (availableWidth - spacing * (_columns - 1)) / _columns);

        var rowHeights = new List<double>();
        for (var index = 0; index < InternalChildren.Count; index++)
        {
            var child = InternalChildren[index];
            child.Measure(new Size(_itemWidth, double.PositiveInfinity));
            var row = index / _columns;
            while (rowHeights.Count <= row) rowHeights.Add(0);
            rowHeights[row] = Math.Max(rowHeights[row], child.DesiredSize.Height);
        }

        var desiredHeight = rowHeights.Sum() + Math.Max(0, rowHeights.Count - 1) * spacing;
        return new Size(availableWidth, desiredHeight);
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        var spacing = Math.Max(0, ItemSpacing);
        if (InternalChildren.Count == 0) return finalSize;

        _itemWidth = Math.Max(0, (finalSize.Width - spacing * (_columns - 1)) / _columns);
        var rowHeights = new double[(InternalChildren.Count + _columns - 1) / _columns];
        for (var index = 0; index < InternalChildren.Count; index++)
            rowHeights[index / _columns] = Math.Max(rowHeights[index / _columns], InternalChildren[index].DesiredSize.Height);

        var rowY = new double[rowHeights.Length];
        for (var row = 1; row < rowHeights.Length; row++)
            rowY[row] = rowY[row - 1] + rowHeights[row - 1] + spacing;

        for (var index = 0; index < InternalChildren.Count; index++)
        {
            var row = index / _columns;
            var column = index % _columns;
            var x = column * (_itemWidth + spacing);
            InternalChildren[index].Arrange(new Rect(x, rowY[row], _itemWidth, rowHeights[row]));
        }

        return finalSize;
    }
}
