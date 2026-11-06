#nullable enable
using SkiaSharp;
using Svg.Skia;
using System.Text.Json;
using System.Xml.Linq;

if (args.Length >= 2 && args[0] == "--inspect")
{
    var sourcePath = args[1];
    using var inspectSvg = new SKSvg();
    inspectSvg.FromSvg(File.ReadAllText(sourcePath));
    var inspectPicture = inspectSvg.Picture ?? throw new InvalidDataException("SVG has no picture");
    var rect = inspectPicture.CullRect;
    var xml = XDocument.Load(sourcePath);
    var svgRoot = xml.Root ?? throw new InvalidDataException("SVG has no root element");
    var result = new
    {
        sourcePath,
        status = "PASS",
        renderer = "Svg.Skia 5.2.3",
        cullBounds = new { left = rect.Left, top = rect.Top, right = rect.Right, bottom = rect.Bottom,
            width = rect.Width, height = rect.Height },
        widthAttribute = (string?)svgRoot.Attribute("width"),
        heightAttribute = (string?)svgRoot.Attribute("height"),
        viewBox = (string?)svgRoot.Attribute("viewBox"),
        elementCounts = xml.Descendants().GroupBy(node => node.Name.LocalName)
            .ToDictionary(group => group.Key, group => group.Count())
    };
    Console.WriteLine(JsonSerializer.Serialize(result));
    return;
}

if (args.Length >= 5 && args[0] == "--render-canvas")
{
    var sourcePath = args[1];
    var outputPath = args[2];
    var canvasWidth = int.Parse(args[3]);
    var canvasHeight = int.Parse(args[4]);
    using var canvasSvg = new SKSvg();
    canvasSvg.FromSvg(File.ReadAllText(sourcePath));
    var canvasPicture = canvasSvg.Picture ?? throw new InvalidDataException("SVG has no picture");
    var xml = XDocument.Load(sourcePath);
    var root = xml.Root ?? throw new InvalidDataException("SVG has no root element");
    var viewBoxValues = ((string?)root.Attribute("viewBox") ?? string.Empty)
        .Split(new[] { ' ', ',', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
        .Select(float.Parse).ToArray();
    if (viewBoxValues.Length != 4 || viewBoxValues[2] <= 0 || viewBoxValues[3] <= 0)
        throw new InvalidDataException("SVG viewBox is missing or invalid");
    var canvasScale = Math.Min(canvasWidth / viewBoxValues[2], canvasHeight / viewBoxValues[3]);
    var offsetX = (canvasWidth - viewBoxValues[2] * canvasScale) / 2f;
    var offsetY = (canvasHeight - viewBoxValues[3] * canvasScale) / 2f;
    using var canvasBitmap = new SKBitmap(new SKImageInfo(canvasWidth, canvasHeight, SKColorType.Rgba8888, SKAlphaType.Premul));
    using (var drawCanvas = new SKCanvas(canvasBitmap))
    {
        drawCanvas.Clear(SKColors.Transparent);
        drawCanvas.Translate(offsetX, offsetY);
        drawCanvas.Scale(canvasScale);
        drawCanvas.Translate(-viewBoxValues[0], -viewBoxValues[1]);
        drawCanvas.DrawPicture(canvasPicture);
        drawCanvas.Flush();
    }
    using var canvasImage = SKImage.FromBitmap(canvasBitmap);
    using var canvasEncoded = canvasImage.Encode(SKEncodedImageFormat.Png, 100);
    File.WriteAllBytes(outputPath, canvasEncoded.ToArray());
    Console.WriteLine(JsonSerializer.Serialize(new { status = "PASS", outputPath, width = canvasWidth, height = canvasHeight, viewBox = viewBoxValues }));
    return;
}

if (args.Length < 2) throw new ArgumentException("Usage: VectorDiagnostics input.svg output.png [width]");
using var svg = new SKSvg();
svg.FromSvg(File.ReadAllText(args[0]));
var picture = svg.Picture ?? throw new InvalidDataException("SVG has no picture");
var bounds = picture.CullRect;
var width = args.Length > 2 ? int.Parse(args[2]) : 1108;
var scale = width / bounds.Width;
using var bitmap = new SKBitmap(new SKImageInfo(width, (int)Math.Ceiling(bounds.Height * scale), SKColorType.Rgba8888, SKAlphaType.Premul));
using (var canvas = new SKCanvas(bitmap))
{
    canvas.Clear(SKColors.Transparent);
    canvas.Scale(scale);
    canvas.Translate(-bounds.Left, -bounds.Top);
    canvas.DrawPicture(picture);
    canvas.Flush();
}
using var image = SKImage.FromBitmap(bitmap);
using var encoded = image.Encode(SKEncodedImageFormat.Png, 100);
File.WriteAllBytes(args[1], encoded.ToArray());
Console.WriteLine(args[1]);
