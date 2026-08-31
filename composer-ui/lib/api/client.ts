import axios from "axios";

// No auth interceptor - unlike gustavo-ui's client, composer has no auth
// system of its own today (Streamlit's version had none either).
const apiClient = axios.create({
  baseURL: "/api",
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

export default apiClient;
