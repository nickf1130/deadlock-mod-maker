import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);

if (!window.studio) {
  root.render(
    <main className="boot-screen startup-failure">
      <div className="brand-mark">!</div>
      <h1>Deadlock Mod Maker could not start</h1>
      <p>The secure desktop bridge did not load. Close the app and run the latest packaged build.</p>
    </main>
  );
} else {
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
