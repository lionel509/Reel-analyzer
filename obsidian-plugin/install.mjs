/** Copy the built plugin into the umbrella vault's plugin folder.
 *
 *  Reel watching happens in the ~/Documents super-brain vault, not in Citadel —
 *  Citadel holds the code and gets the graphify viewer instead.
 */
import { copyFile, mkdir } from "node:fs/promises";
import { join } from "node:path";

/** Override the target vault with OBSIDIAN_VAULT. */
const VAULT = process.env.OBSIDIAN_VAULT ?? "/Users/lionelweng/Documents";
const TARGET = join(VAULT, ".obsidian/plugins/reel-analyzer");

await mkdir(TARGET, { recursive: true });
for (const file of ["main.js", "manifest.json", "styles.css"]) {
  await copyFile(file, join(TARGET, file));
  console.log(`installed ${file}`);
}
console.log(`\n-> ${TARGET}`);
console.log("Reload Obsidian, then enable 'Reel Analyzer' in Community Plugins.");
