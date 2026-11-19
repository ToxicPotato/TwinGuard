# TwinGuard

TwinGuard is an open-source workbench for cybersecurity experiments in
leader–follower vehicle platooning. It runs a simulated robot platoon, injects
attacks into the vehicle-to-vehicle (V2V) messages, monitors the vehicles'
telemetry with digital twin components, and records each run together with a
risk assessment.

Attacks are injected outside the monitoring pipeline: the monitors only see
what the vehicles report, so clean and attacked runs are processed in exactly
the same way.

> **Paper:** *TwinGuard: An Extensible Workbench for Cybersecurity
> Experimentation in Vehicular Platooning* (submitted to EnCyCriS 2027).
> The tag [`v1.0`](../../tree/v1.0) is the version described in the paper.

## Components

| Folder | What it is |
|---|---|
| `Unreal/TwinGuard` | Simulated three-vehicle platoon (Unreal Engine 5.7). Each vehicle is an MQTT client that publishes on `vehicle/<id>/…` and listens on `actions/<id>/…`. |
| `visualization/tamper-service` | Tamper relay: forwards `vehicle/#` to `actions/#` and rewrites selected fields while an attack is active (velocity spoofing, false braking). |
| `visualization/backend` | Backend (FastAPI): ingestion adapters, canonical frames, TwinRunner, recordings, risk layer, and the API used by all clients. |
| `visualization/python` | Monitors: LowRes and HighRes digital twins and ScenarioTwin (velocity consistency check). |
| `visualization/report-service` | Turns a dataset into an HTML report. |
| `visualization/twinbench` | Experiment client (React): start attacks, record runs, inspect risk findings. |
| `visualization/frontend` | Visualization client (Svelte): live and offline view of runs. |
| `experiments` | Scripted experiments and analysis, including the case study from the paper. |

## Requirements

- Windows 10/11
- Unreal Engine 5.7
- Docker Desktop
- An MQTT broker on the host, port 1883 (for example Mosquitto)
- Python 3.10 or later (for the experiment scripts)

## Quick start

1. Start the MQTT broker.
2. Start the relay, backend, report service, and both web clients:
   ```
   docker compose -f visualization/docker-compose.yml up -d --build
   ```
3. Open `Unreal/TwinGuard/TwinGuard.uproject` in Unreal Engine 5.7 and start
   the simulation (`LVL_Main`). Switch the followers to platooning.
4. Open the clients:
   - Experiment client: http://localhost:5174
   - Visualization client: http://localhost:5173
   - Backend API and its OpenAPI docs: http://localhost:8000/docs

If you do not have the BlueprintAssist editor plugin, set `"Enabled": false`
for it in `Unreal/TwinGuard/TwinGuard.uproject`. It only affects the editor,
not the simulation.

**Security note:** the APIs have no authentication and the relay accepts
commands from the network. Run TwinGuard only on an isolated lab network. The
paper's security analysis lists the threats and mitigations.

## Reproducing the case study

With the platoon running and the followers platooning:

```
pip install -r experiments/requirements.txt
python experiments/run_within_threshold_trials.py --max-trials 50 --output-root visualization/output/case-study
python experiments/case_study_summary.py --experiment-dir visualization/output/case-study/outside_threshold_trials
python experiments/plot_case_study_trials.py --experiment-dir visualization/output/case-study/outside_threshold_trials --out case_trials.pdf
```

The runner mixes velocity spoofing, false braking, and no-attack trials
(configuration: `experiments/scenarios/outside_threshold_trials.yaml`). The
summary script derives detections, time to detection, false positives, and the
followers' reaction directly from the recorded frames and prints the rows of
the results table. Recordings are written to `visualization/output/`.

## Offline mode

Exported telemetry spreadsheets (`.xlsx`) can be uploaded in the
visualization client (or `POST /datasets/upload`) and are processed by the
same monitoring pipeline as live data.

## Related repository

The Simulink vehicle controller, the Simulink–Unreal co-simulation, and the
example datasets are in
[TwinGuard-Sim-CoSim](https://github.com/ToxicPotato/TwinGuard-Sim-CoSim)
(Apache 2.0).

## License

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
Third-party components, such as the Paho MQTT plugin in
`Unreal/TwinGuard/Plugins/PahoMQTT`, keep their own licenses.
