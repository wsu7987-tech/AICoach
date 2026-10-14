import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";

import App from "./App.vue";
import "./styles.css";
import "./config-center.css";
import "./model-management.css";
import "./intent-recognition.css";

createApp(App).use(ElementPlus).mount("#app");
