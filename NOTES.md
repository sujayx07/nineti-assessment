# Notes

## Time spent

About 4 hours, including implementation, testing, and debugging.

## Q1 — My approach (3–5 sentences)

I skip invalid readings, parse timestamps with their UTC offsets, and keep the last reading for duplicate instants. The valid readings are sorted and processed in pairs, including counter resets and the 20 kW glitch limit. Consumption is assigned to the later reading's Europe/Berlin date and returned as rounded kWh totals.

## Q2 — My approach (3–5 sentences)

`MeterClient` uses the supplied `aiohttp` session, token header, and five-second request timeout. It validates successful responses and converts them into `MeterStatus`, while authentication and protocol errors stop immediately. 503 responses, timeouts, and connection errors follow the required retry schedule; I also included the optional `Retry-After` and tool-wrapper features.

## One mistake or bug you hit, and how you found it

I initially used the last raw counter value instead of each day's accumulated total in Q1. The specification example exposed this, so I corrected the final conversion. A Q2 test also caught an extra retry-delay lookup after the final attempt.

## Which rule or edge case was hardest, and why

The hardest rule was the Europe/Berlin daylight-saving boundary. I had to calculate elapsed time from the actual timezone-aware instants, but assign each interval using the later reading's local date.

## Tools used

I used Python documentation and the `datetime`, `zoneinfo`, `aiohttp`, and `aioresponses` documentation. I also used AI assistance to discuss the specification, draft parts of the code and tests, and review edge cases and also used for writting these NOTES.md file based on my informations. I reviewed the results, made corrections, and ran the tests myself.
