import Foundation

struct Point {
    var lat: Double
    var lon: Double
}

enum Geometry {
    static let earthRadius = 6_371_008.8
    static let radians = Double.pi / 180
    static func distance(_ a: Point, _ b: Point) -> Double {
        let dLat = (b.lat - a.lat) * radians
        let dLon = (b.lon - a.lon) * radians
        let v = pow(sin(dLat / 2), 2) + cos(a.lat * radians) * cos(b.lat * radians) * pow(sin(dLon / 2), 2)
        return 2 * earthRadius * asin(min(1, sqrt(max(0, v))))
    }
    static func heading(_ a: Point, _ b: Point) -> Double {
        let p = a.lat * radians, q = b.lat * radians, dl = (b.lon - a.lon) * radians
        return (atan2(sin(dl) * cos(q), cos(p) * sin(q) - sin(p) * cos(q) * cos(dl)) / radians + 360)
            .truncatingRemainder(dividingBy: 360)
    }
    static func angleDifference(_ a: Double, _ b: Double) -> Double {
        let d = abs(a - b).truncatingRemainder(dividingBy: 360)
        return min(d, 360 - d)
    }
    static func interpolate(_ a: Point, _ b: Point, _ f: Double) -> Point {
        Point(lat: a.lat + f * (b.lat - a.lat), lon: a.lon + f * (b.lon - a.lon))
    }
}

struct Projection {
    let edgeId: String
    let offset: Double
    let point: Point
    let distance: Double
    let heading: Double
}

struct EdgeGeometry {
    let points: [Point]
    let cumulative: [Double]
    let length: Double
    init(_ edge: NetworkEdge) {
        points = edge.coordinates.map { Point(lat: $0[0], lon: $0[1]) }
        var c = [0.0]
        for i in 1..<points.count { c.append(c.last! + Geometry.distance(points[i - 1], points[i])) }
        let rawLength = c.last!
        cumulative = edge.pointMeasuresM ?? c.map { $0 / rawLength * edge.lengthM }
        length = edge.lengthM
    }
    func point(at offset: Double) -> Point {
        let m = min(length, max(0, offset))
        for i in 1..<points.count where cumulative[i] >= m {
            let segment = cumulative[i] - cumulative[i - 1]
            return Geometry.interpolate(points[i - 1], points[i], segment > 0 ? (m - cumulative[i - 1]) / segment : 0)
        }
        return points.last!
    }
    func project(_ point: Point, edgeId: String) -> Projection {
        var best: Projection?
        for i in 1..<points.count {
            let a = points[i - 1], b = points[i]
            let cosLat = cos(point.lat * Geometry.radians)
            let dx = (b.lon - a.lon) * cosLat, dy = b.lat - a.lat
            let px = (point.lon - a.lon) * cosLat, py = point.lat - a.lat
            let denominator = dx * dx + dy * dy
            let f = denominator > 0 ? max(0, min(1, (px * dx + py * dy) / denominator)) : 0
            let projected = Geometry.interpolate(a, b, f)
            let distance = Geometry.distance(point, projected)
            if best == nil || distance < best!.distance {
                best = Projection(edgeId: edgeId, offset: cumulative[i - 1] + f * (cumulative[i] - cumulative[i - 1]),
                                  point: projected, distance: distance, heading: Geometry.heading(a, b))
            }
        }
        return best!
    }
}
