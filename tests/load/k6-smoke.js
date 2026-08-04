import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  scenarios: {
    readiness: {
      executor: "constant-arrival-rate",
      rate: 25,
      timeUnit: "1s",
      duration: "2m",
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500", "p(99)<1000"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8100";

export default function () {
  const response = http.get(`${baseUrl}/healthz`, {
    headers: { "X-Request-Id": `k6-${__VU}-${__ITER}` },
  });
  check(response, {
    "health is 200": (result) => result.status === 200,
    "request id is returned": (result) => Boolean(result.headers["X-Request-Id"]),
  });
  sleep(0.1);
}
