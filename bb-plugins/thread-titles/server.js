import { hostContract } from "./contract.js";
import { registerAppleTitles } from "./service.js";

export default function plugin(bb) {
  const host = bb.hosts.experimental_client({ contract: hostContract });

  async function primaryHostId() {
    return (await bb.sdk.system.config()).primaryHostId;
  }

  registerAppleTitles(bb, {
    async complete(prompt, signal) {
      const hostId = await primaryHostId();
      if (hostId === null) throw new Error("No primary machine is connected");
      return host.call("titles.complete", { prompt }, { hostId, signal });
    },
    async status() {
      const hostId = await primaryHostId();
      if (hostId === null) return { ready: false, message: "No primary machine is connected" };
      return host.call("titles.status", {}, { hostId, timeoutMs: 5000 });
    },
  });
}
