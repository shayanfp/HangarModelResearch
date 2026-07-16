# A Computationally Resilient Continuous-Time MILP for Integrated Aircraft Hangar Scheduling and Layout

This repository contains the data, mathematical models, and source code for the research paper **"A Computationally Resilient Continuous-Time MILP for Integrated Aircraft Hangar Scheduling and Layout"**. 

It includes the exact Mixed-Integer Linear Programming (MILP) model implemented in **GAMS**, a heuristic algorithm (**MANAGER**) implemented in **Python**, extensive benchmark datasets, and a custom **Decision Support System (DSS) dashboard** to render hangar layouts.

---

## 📂 Repository Structure

The project is structured to seamlessly separate raw data, mathematical formulations, runners, and result outputs:

* **`/data/`**: Contains all input data instances required to run the models, carefully categorized into subsets:
  * `incremental/`: Instances evaluating the growth of the problem size.
  * `random/`: Generalized random benchmark datasets.
  * `congestion/`: Scalability tests evaluating the model under tight scheduling bounds (1.0x to 3.3x).
  * `case2015/`: A real-world case study without initial hangar occupancy.

* **`/src/`**: Contains the core mathematical and algorithmic engines:
  * `gams_model.gms`: The primary GAMS implementation of the exact MILP optimization model.
  * `gams_model_case2015.gms`: The GAMS implementation tailored for the empty-initial-state case study.
  * `MANAGER_heuristic.py`: The core algorithm for our Python-based heuristic approach.
  * `visualization_tool.py`: A Python graphical tool to render and visualize the generated solution layouts.

* **Root Scripts (`run_*.py`)**: Python orchestrators designed for clean and automated batch execution of the GAMS and heuristic models.
  
* **`/results/`**: Contains the pre-computed solution files (`.csv` and `.xlsx`) for all computational instances discussed in the paper.

---

## 🚀 Getting Started

### Prerequisites

Ensure you have the following software installed:
1. **Python 3.x**: Required for the execution runners, the heuristic algorithm, and the visualization tool.
2. **GAMS**: The General Algebraic Modeling System with the **CPLEX** solver is required if you wish to re-run the MILP models from scratch. Ensure GAMS is added to your system's `PATH`.

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/shayanfp/HangarModelResearch.git
   cd HangarModelResearch
   ```

2. **Install Python dependencies:**
   A standard `requirements.txt` file is provided to automatically install all required packages (such as `pandas`, `numpy`, `matplotlib`, and `openpyxl`).
   ```bash
   pip install -r requirements.txt
   ```

---

## 🛠️ How to Run the Experiments

Instead of relying on long manual command-line arguments, we provide automated Python runners that flawlessly orchestrate GAMS execution, manage log parsing, and extract `.csv` solutions into the `/results` directory.

### 1. Running the Exact MILP Model (GAMS)
You can selectively run any subset of the computational experiments by executing the respective Python orchestrator:

```bash
python run_incremental.py
python run_random.py
python run_congestion.py
python run_case2015.py
```
> **Note:** These scripts automatically handle GDX data compilation, CPLEX time limits (`reslim`), and optimality gaps (`optcr`).

### 2. Running the MANAGER Heuristic
The heuristic script runs in batch mode, processing the entire dataset autonomously. It generates individual `.csv` layout files as well as comprehensive `.xlsx` summary reports.

```bash
python run_all_heuristic.py
```

---

## 📊 Visualizing the Results

**This repository provides pre-computed results so you can visualize the optimal layouts without running the CPLEX solver.**

You can use the `visualization_tool.py` to view any solution `.csv` file (from either the MILP model or the MANAGER heuristic). The tool generates a highly detailed graphical representation of the aircraft hangar layout and scheduling timeline.

* **Option A: Run by providing a file path (recommended):**
  ```bash
  # Visualize a MILP solution for a random instance
  python src/visualization_tool.py --file results/random/SolutionReport_N20_S01.csv
  
  # Visualize a Heuristic solution for an incremental instance
  python src/visualization_tool.py --file results/MANAGER_heuristic/incremental/Heuristic_Solution_INC-N020_S01.csv
  ```

* **Option B: Run without arguments:**
  Executing the script without arguments opens a graphical file selector, allowing you to choose the `.csv` solution file manually.
  ```bash
  python src/visualization_tool.py
  ```

---

## 📜 Citation & License

This project is licensed under the MIT License. If you utilize our mathematical formulation, datasets, or the MANAGER heuristic in your academic work, please consider citing our paper (citation details will be updated post-publication).