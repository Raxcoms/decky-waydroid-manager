import commonjs from "@rollup/plugin-commonjs";
import resolve from "@rollup/plugin-node-resolve";
import typescript from "@rollup/plugin-typescript";
import esbuild from "rollup-plugin-esbuild";

export default {
  input: "src/index.tsx",
  output: {
    file: "dist/index.js",
    format: "cjs",
    sourcemap: true,
  },
  external: ["react", "react-dom", "react/jsx-runtime", "@decky/ui", "@decky/api"],
  plugins: [resolve(), commonjs(), typescript(), esbuild({ target: "es2022" })],
};
