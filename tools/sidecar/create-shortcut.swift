import Foundation

func shellQuote(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

guard CommandLine.arguments.count == 5 else {
    fputs("Usage: xcrun swift create-shortcut.swift HOST USER IPAD_NAME OUTPUT_DIRECTORY\n", stderr)
    exit(1)
}
let host = CommandLine.arguments[1]
let user = CommandLine.arguments[2]
let device = CommandLine.arguments[3]
let destination = URL(fileURLWithPath: CommandLine.arguments[4], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)

do {
    let name = "Start iPad Display"
    let script = "exec /usr/bin/caffeinate -u -d -t 45 \"$HOME/.local/bin/sidecar\" connect \(shellQuote(device))"
    let workflow: [String: Any] = [
        "WFWorkflowName": name,
        "WFWorkflowClientVersion": "2106.100.3.1",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": ["WFWorkflowIconStartColor": 463140863, "WFWorkflowIconGlyphNumber": 61446],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
        "WFQuickActionSurfaces": [],
        "WFWorkflowHasShortcutInputVariables": false,
        "WFWorkflowHasOutputFallback": false,
        "WFWorkflowImportQuestions": [[
            "ActionIndex": 1,
            "Category": "Parameter",
            "ParameterKey": "WFSSHPassword",
            "Text": "Enter your Mac login password for \(user) on \(host). You can instead configure SSH Key authentication after importing.",
            "DefaultValue": ""
        ]],
        "WFWorkflowActions": [
            [
                "WFWorkflowActionIdentifier": "is.workflow.actions.comment",
                "WFWorkflowActionParameters": [
                    "WFCommentActionText": "\(name) on \(host) for iPad \(device). The Mac must be reachable on the local network and logged in; keep the iPad awake and unlocked. The Run Script over SSH action below needs your Mac login password or an authorized Shortcuts SSH key. No password is included in this file. Start makes the iPad the primary display at its native Retina resolution, with the Mac monitor mirroring it. It can be run again without disconnecting."
                ]
            ],
            [
                "WFWorkflowActionIdentifier": "is.workflow.actions.runsshscript",
                "WFWorkflowActionParameters": [
                    "UUID": UUID().uuidString,
                    "WFSSHHost": host,
                    "WFSSHPort": "22",
                    "WFSSHUser": user,
                    "WFSSHAuthenticationType": "Password",
                    "WFSSHPassword": "",
                    "WFSSHScript": script
                ]
            ]
        ]
    ]
    let unsigned = destination.appendingPathComponent("\(name).unsigned.shortcut")
    let signed = destination.appendingPathComponent("\(name).shortcut")
    guard !FileManager.default.fileExists(atPath: signed.path) else {
        fputs("Refusing to replace an existing shortcut: \(signed.path)\n", stderr)
        exit(1)
    }
    let data = try PropertyListSerialization.data(fromPropertyList: workflow, format: .xml, options: 0)
    try data.write(to: unsigned, options: .atomic)
    let signer = Process()
    signer.executableURL = URL(fileURLWithPath: "/usr/bin/shortcuts")
    signer.arguments = ["sign", "--mode", "anyone", "--input", unsigned.path, "--output", signed.path]
    try signer.run()
    signer.waitUntilExit()
    guard signer.terminationStatus == 0 else { exit(signer.terminationStatus) }
    try FileManager.default.removeItem(at: unsigned)
    print(signed.path)
}
