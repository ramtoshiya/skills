// Swift source of the helper binary, kept in a string so the plugin build bundles it.
// The Swift code must contain no backtick and no dollar sign followed by a brace.
export const SWIFT_SOURCE = String.raw`import Foundation
import FoundationModels

// Protocol: title-helper status, or title-helper complete with the prompt on stdin.
// Prints one JSON object on stdout and always exits 0 once it has answered.

func emit(_ object: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: object)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

func unavailableMessage(_ reason: SystemLanguageModel.Availability.UnavailableReason) -> String {
    switch reason {
    case .deviceNotEligible: return "This Mac does not support Apple Intelligence"
    case .appleIntelligenceNotEnabled: return "Apple Intelligence is turned off in System Settings"
    case .modelNotReady: return "The Apple on-device model is still downloading or preparing"
    @unknown default: return "The Apple on-device model is unavailable"
    }
}

let model = SystemLanguageModel.default
let mode = CommandLine.arguments.dropFirst().first ?? ""

if case .unavailable(let reason) = model.availability {
    let message = unavailableMessage(reason)
    if mode == "status" { emit(["ready": false, "message": message]) }
    else { emit(["ok": false, "code": "unavailable", "message": message]) }
    exit(0)
}

switch mode {
case "status":
    emit(["ready": true])
case "complete":
    let prompt = String(decoding: FileHandle.standardInput.readDataToEndOfFile(), as: UTF8.self)
    do {
        let session = LanguageModelSession()
        let response = try await session.respond(to: prompt)
        emit(["ok": true, "text": response.content])
    } catch let error as LanguageModelSession.GenerationError {
        let code: String
        if case .guardrailViolation = error { code = "guardrail" } else { code = "generation" }
        emit(["ok": false, "code": code, "message": error.errorDescription ?? String(describing: error)])
    } catch {
        emit(["ok": false, "code": "error", "message": String(describing: error)])
    }
default:
    FileHandle.standardError.write(Data("usage: title-helper status|complete\n".utf8))
    exit(2)
}
`;
