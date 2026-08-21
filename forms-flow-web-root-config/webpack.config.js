const { merge } = require("webpack-merge");
const singleSpaDefaults = require("webpack-config-single-spa");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const CopyPlugin = require("copy-webpack-plugin");
const DefinePlugin = require("webpack/lib/DefinePlugin");
require("dotenv").config({ path: "./.env" });

module.exports = (webpackConfigEnv, argv) => {
  const orgName = "formsflow";
  
  // Log environment variable for debugging
  console.log("=== Webpack Build Environment ===");
  console.log("MF_FORMSFLOW_WEB_URL:", process.env.MF_FORMSFLOW_WEB_URL || "NOT SET");
  console.log("All MF_* env vars:", Object.keys(process.env).filter(k => k.startsWith("MF_")).map(k => `${k}=${process.env[k]}`).join(", "));
  
  const defaultConfig = singleSpaDefaults({
    orgName,
    projectName: "root-config",
    webpackConfigEnv,
    argv,
    disableHtmlGeneration: true,
  });

  return merge(defaultConfig, {
    // modify the webpack config however you'd like to by adding to this object
    plugins: [
      new HtmlWebpackPlugin({
        inject: false,
        template: "src/index.ejs",
        templateParameters: {
          isLocal: webpackConfigEnv && webpackConfigEnv.isLocal,
          orgName,
          // Pass environment variables to EJS template
          // This makes process.env available in the EJS template
          process: {
            env: {
              ...process.env,
              // Ensure MF_FORMSFLOW_WEB_URL is available, default to /mf/forms-flow-web.js
              MF_FORMSFLOW_WEB_URL: process.env.MF_FORMSFLOW_WEB_URL || "/mf/forms-flow-web.js",
            },
          },
        },
      }),
      new CopyPlugin({
        patterns: [
          {
            from: "./public/",
            globOptions: {
              dot: true,
              gitignore: true,
              ignore: ["index.html"],
            },
          },
        ],
      }),
      new DefinePlugin({
        "process.env": JSON.stringify(process.env),
      }),
    ],
  });
};
