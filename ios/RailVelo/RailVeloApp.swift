import SwiftUI

@main
struct RailVeloApp: App {
    @StateObject private var model = RideViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .tint(.cyan)
        }
    }
}
