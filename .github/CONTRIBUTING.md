# Contributing to Garmin-Grafana

Thank you for considering contributing to **Garmin-Grafana**! Your support helps enhance this open-source project.

## Table of Contents

* [Getting Started](#getting-started)
* [How to Contribute](#how-to-contribute)
  * [Reporting Bugs](#reporting-bugs)
  * [Suggesting Enhancements](#suggesting-enhancements)
  * [Submitting Pull Requests](#submitting-pull-requests)
* [Code Style Guidelines](#code-style-guidelines)
* [Project Structure](#project-structure)
* [Community and Support](#community-and-support)
* [License](#license)

## Getting Started

To set up the project locally:

1. **Clone the repository:**

   ```bash
   git clone https://github.com/arpanghosh8453/garmin-grafana.git
   cd garmin-grafana
   ```
2. **Install dependencies:**

   Ensure you have Python 3.12+ and uv package manager installed. Then, install the required packages:

   ```bash
   uv sync --locked
   ```

   Alternatively, you can use the `pyproject.toml` file to install the dependencies with pip.  
   
3. **Configure environment variables:**

   Create a `override-default-vars.env` file in the root directory and add necessary ENV variables (make sure to add this to the .gitignore file so you don't accidentally commit that file). You can also export the ENV varibles to the shell environment directly.  
   
4. **Set up external InfluxDB and Grafana with Containers**

   You should deploy an external InfluxDB database and Grafana container for full test environment setup. This is important if you are adding now measurement or modifying an existing one.  
   
5. **Run the application:**

   ```bash
   uv run src/garmin_grafana/garmin_fetch.py
   ```
   
   This should start fetching data from Garmin and populate your InfluxDB database.
   

## How to Contribute

### Reporting Bugs

If you encounter any bugs or issues:

* **Search existing issues:** Before creating a new issue, check if it has already been reported.
* **Create a detailed issue:** If it's a new bug, open an issue with the following details:

  * **Title:** Brief and descriptive.
  * **Description:** Detailed explanation of the bug.
  * **Steps to Reproduce:** How can we replicate the issue?
  * **Expected Behavior:** What did you expect to happen?
  * **Screenshots:** If applicable.
  * **Environment:** OS, Python version, Docker version, etc.

### Suggesting Enhancements

We welcome suggestions to improve the project:

* **Check existing feature requests:** Ensure your idea hasn't been proposed already.
* **Open a new issue:** Provide a clear and concise description of the enhancement, its benefits, and any potential drawbacks.

### Submitting Pull Requests

We appreciate your efforts to improve the project. Contributions are always apprciated but if you are planning to develop a new feature that does not exist or improve one that you find useful, please open an issue first to make sure we are on the same page before you start investing your time. This way, the communication stays clear and the feature would integrate to the codebase smoother.

Please test the code execution before opening an PR request and include a message in the PR request description that you have tested the new code. It saves the review time.

[!IMPORTANT]
For significant changes, it's always advised to discuss them via an issue before starting work.

## Code Style Guidelines

Please maintain the existing code flow and check examples when implementing a similar one. It will preserve consistancy and readablity.

## Project Structure

Understanding the repository layout:

```
garmin-grafana/
├── .github/               # GitHub-specific files (e.g., issue templates)
├── Extra/                 # Additional scripts and resources
├── Grafana_Dashboard/     # Pre-configured Grafana dashboards
├── Grafana_Datasource/    # Grafana data source configurations
├── src/garmin_grafana/    # Main application source code
├── .gitignore             # Git ignore rules
├── Dockerfile             # Docker configuration
├── README.md              # Project overview and instructions
├── compose-example.yml    # Docker Compose example
├── easy-install.sh        # Installation script
├── pyproject.toml         # Project metadata and dependencies
└── uv.lock                # Locked dependencies
```

## Community and Support

Join our community to collaborate and seek assistance:

* **Discussions:** Engage in project-related discussions on the [GitHub Discussions](https://github.com/arpanghosh8453/garmin-grafana/discussions) page.
* **Issues:** Report bugs or suggest features via the [Issues](https://github.com/arpanghosh8453/garmin-grafana/issues) tab.
* **Reddit:** Participate in conversations on [r/Garmin](https://www.reddit.com/r/Garmin)

## License

This project is licensed under the [BSD-3-Clause License](../LICENSE). By contributing, you agree that your contributions will be licensed under this license. You will be attributed for your contribution.

---

We appreciate your interest in contributing to Garmin-Grafana. Your efforts help make this project better for everyone!

---
