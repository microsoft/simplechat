// admin_model_catalog.js
import { mountModelCatalog } from "./model_catalog_ui.js";

const root = document.getElementById("model-catalog-manager");
if (root) mountModelCatalog(root);
