// openclaw-register.swift — SMAppService register/unregister/status helper.
//
// macOS Sequoia (and later) presents Login Items / Background Items
// based on whether a LaunchAgent was registered via SMAppService
// (modern, "this agent belongs to this .app", grouped under bundle
// display name) or by manually dropping a plist into
// ~/Library/LaunchAgents/ (legacy, "this agent is from this developer",
// grouped under the cert team display name).
//
// We want the modern presentation. SMAppService is a Swift-only API,
// so this minimal helper is compiled to a native Mach-O and embedded
// at Contents/MacOS/openclaw-register inside both Bridge.app and
// Relay.app. The pkg's postinstall and the .app's first launch invoke
// it to register / unregister the bundled LaunchAgent plist.
//
// Usage:
//     openclaw-register register   <plist-name-relative-to-Contents>
//     openclaw-register unregister <plist-name-relative-to-Contents>
//     openclaw-register status     <plist-name-relative-to-Contents>
//
// Examples (called from Bridge.app's binary path):
//     openclaw-register register   Contents/Library/LaunchAgents/me.lopes.openclaw.bridge.plist
//     openclaw-register status     Contents/Library/LaunchAgents/me.lopes.openclaw.bridge.plist
//
// Exit codes:
//     0  success / agent already in desired state
//     1  SMAppService error (printed to stderr)
//     2  bad arguments
//
// Build:
//     xcrun swiftc -O \
//         -target arm64-apple-macos14.0 \
//         -framework ServiceManagement \
//         -o openclaw-register openclaw-register.swift

import Foundation
import ServiceManagement

func usage() -> Never {
    let msg = """
    usage: openclaw-register <register|unregister|status> <plist-name>
        plist-name is relative to the .app's Contents/ directory
        e.g.: Contents/Library/LaunchAgents/me.lopes.openclaw.bridge.plist
    """
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    exit(2)
}

let args = CommandLine.arguments
guard args.count == 3 else { usage() }

let action = args[1]
let plistName = args[2]
let agent = SMAppService.agent(plistName: plistName)

func statusString(_ s: SMAppService.Status) -> String {
    switch s {
    case .notRegistered:    return "notRegistered"
    case .enabled:          return "enabled"
    case .requiresApproval: return "requiresApproval"
    case .notFound:         return "notFound"
    @unknown default:       return "unknown(\(s.rawValue))"
    }
}

do {
    switch action {
    case "register":
        try agent.register()
        print("ok register \(plistName) status=\(statusString(agent.status))")
    case "unregister":
        try agent.unregister()
        print("ok unregister \(plistName) status=\(statusString(agent.status))")
    case "status":
        print("status \(plistName) \(statusString(agent.status))")
    default:
        usage()
    }
} catch {
    let nsError = error as NSError
    let msg = "error \(action) \(plistName): \(nsError.domain) \(nsError.code) \(nsError.localizedDescription)"
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    exit(1)
}
