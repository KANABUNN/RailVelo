import Foundation
import RailVeloCore
#if canImport(CoreLocation)
import CoreLocation

public extension Observation {
    init(location: CLLocation) {
        self.init(timestamp: location.timestamp.timeIntervalSince1970,
                  lat: location.coordinate.latitude, lon: location.coordinate.longitude,
                  horizontalAccuracyM: location.horizontalAccuracy,
                  speedMps: location.speed >= 0 ? location.speed : nil,
                  speedAccuracyMps: location.speedAccuracy >= 0 ? location.speedAccuracy : nil,
                  courseDeg: location.course >= 0 ? location.course : nil)
    }
}

/// Sensor collection only. Keep one MapMatcher per trip on one serial executor.
/// The host app supplies NSLocationWhenInUseUsageDescription and requests permission.
@MainActor
public final class CoreLocationSource: NSObject, CLLocationManagerDelegate {
    public var onObservations: (([Observation]) -> Void)?
    public var onFailure: ((String) -> Void)?
    public var onAuthorizationChange: ((CLAuthorizationStatus) -> Void)?
    private let manager: CLLocationManager

    public override init() {
        manager = CLLocationManager()
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
        // Fresh stationary fixes are required to establish continuous station dwell.
        manager.distanceFilter = kCLDistanceFilterNone
        manager.activityType = .otherNavigation
        manager.pausesLocationUpdatesAutomatically = false
    }
    public var authorizationStatus: CLAuthorizationStatus { manager.authorizationStatus }
    public var hasPreciseLocation: Bool { manager.accuracyAuthorization == .fullAccuracy }
    public func requestWhenInUseAuthorization() { manager.requestWhenInUseAuthorization() }
    public func start() {
        #if os(macOS)
        guard manager.authorizationStatus == .authorizedAlways else { return }
        #else
        guard manager.authorizationStatus == .authorizedAlways || manager.authorizationStatus == .authorizedWhenInUse else { return }
        #endif
        #if os(iOS)
        // The host declares UIBackgroundModes/location. Only an active ride enables it.
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        #endif
        manager.startUpdatingLocation()
    }
    public func stop() {
        manager.stopUpdatingLocation()
        #if os(iOS)
        manager.allowsBackgroundLocationUpdates = false
        #endif
    }

    nonisolated public func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let observations = locations.map(Observation.init(location:))
        Task { @MainActor [weak self] in self?.onObservations?(observations) }
    }
    nonisolated public func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        let detail = error.localizedDescription
        Task { @MainActor [weak self] in self?.onFailure?(detail) }
    }
    nonisolated public func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor [weak self] in self?.onAuthorizationChange?(status) }
    }
}
#endif
