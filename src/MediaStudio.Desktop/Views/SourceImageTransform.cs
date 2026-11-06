using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.Views;

/// <summary>Uniform-fit source pixel to WPF device-independent viewport mapping.</summary>
public readonly record struct SourceImageTransform(
    int SourceWidth,
    int SourceHeight,
    double ViewWidth,
    double ViewHeight,
    double Zoom = 1.0,
    double PanX = 0.0,
    double PanY = 0.0)
{
    public double Scale
    {
        get
        {
            if (SourceWidth <= 0 || SourceHeight <= 0 || ViewWidth <= 0 || ViewHeight <= 0)
            {
                return 0;
            }
            return Math.Min(ViewWidth / SourceWidth, ViewHeight / SourceHeight) * Math.Clamp(Zoom, 0.05, 32.0);
        }
    }

    public double ImageLeft => (ViewWidth - SourceWidth * Scale) / 2.0 + PanX;
    public double ImageTop => (ViewHeight - SourceHeight * Scale) / 2.0 + PanY;
    public double ImageViewWidth => SourceWidth * Scale;
    public double ImageViewHeight => SourceHeight * Scale;

    public (double X, double Y) SourceToView(double sourceX, double sourceY) =>
        (ImageLeft + sourceX * Scale, ImageTop + sourceY * Scale);

    public bool TryViewToSource(double viewX, double viewY, out SourceImagePoint point)
    {
        point = default;
        if (!TryViewToSource(viewX, viewY, out double sourceX, out double sourceY)) return false;
        point = new SourceImagePoint((int)Math.Floor(sourceX), (int)Math.Floor(sourceY));
        return true;
    }

    public bool TryViewToSource(double viewX, double viewY, out double sourceX, out double sourceY)
    {
        sourceX = 0;
        sourceY = 0;
        if (Scale <= 0)
        {
            return false;
        }

        sourceX = (viewX - ImageLeft) / Scale;
        sourceY = (viewY - ImageTop) / Scale;
        if (!double.IsFinite(sourceX) || !double.IsFinite(sourceY)
            || sourceX < 0 || sourceY < 0 || sourceX >= SourceWidth || sourceY >= SourceHeight)
        {
            return false;
        }
        return true;
    }

    public double ViewRadiusToSource(double viewRadius) => Scale > 0 ? viewRadius / Scale : 0;
}

public readonly record struct SourceImagePoint(int X, int Y);
public readonly record struct SourceImageCoordinate(double X, double Y);
