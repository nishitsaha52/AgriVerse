import { spawn } from "node:child_process";
import { loadEnvFile } from "node:process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

// Load shared configuration before Next chooses a port or reads server variables.
// Existing shell/hosting environment variables take precedence over the file.
try {
  loadEnvFile(new URL("../../../.env", import.meta.url));
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

const [command, ...args] = process.argv.slice(2);
if (
  ["dev", "start"].includes(command) &&
  !args.some((arg) => arg === "-p" || arg === "--port" || arg.startsWith("--port="))
) {
  args.push("--port", process.env.PORT || process.env.WEB_PORT || "3001");
}

const require = createRequire(import.meta.url);
const child = spawn(process.execPath, [require.resolve("next/dist/bin/next"), command, ...args], {
  cwd: fileURLToPath(new URL("..", import.meta.url)),
  stdio: "inherit",
  env: process.env,
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code ?? 1;
});
