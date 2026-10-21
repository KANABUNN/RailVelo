import SwiftUI

@main
struct RailVeloApp: App {
    @StateObject private var model = RideViewModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .tint(.cyan)
                .onAppear { recordPhase(scenePhase) }
                .onChange(of: scenePhase) { phase in
                    recordPhase(phase)
                }
        }
    }

    private func recordPhase(_ phase: ScenePhase) {
        switch phase {
        case .active: model.recordApplicationPhase("active")
        case .inactive: model.recordApplicationPhase("inactive")
        case .background: model.recordApplicationPhase("background")
        @unknown default: break
        }
    }
}
