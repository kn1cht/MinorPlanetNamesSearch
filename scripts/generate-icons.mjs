/** Generate static brand icons from the Font Awesome icon library. */
import { mkdirSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { faGithub } from "@fortawesome/free-brands-svg-icons";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const assetDir = join(root, "web", "assets");
const [width, height, , , pathData] = faGithub.icon;
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}"><path d="${pathData}"/></svg>\n`;

mkdirSync(assetDir, { recursive: true });
writeFileSync(join(assetDir, "github.svg"), svg);
console.log("✅ Generated web/assets/github.svg");
