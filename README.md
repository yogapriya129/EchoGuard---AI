EchoGuard AI

An AI-assisted college request management system

About the Project

EchoGuard AI is a web-based application designed to help organise and track college-related requests. It brings request information, status tracking, and rule-based analysis together in one interface.

The project aims to make college request management more organised and help users identify requests that may need attention.

Problem Statement

College students submit requests for certificates and other administrative services. Tracking their progress, pending actions, and expected completion dates can become difficult when information is spread across different places.

EchoGuard AI aims to provide a centralised platform for managing and monitoring these requests.

Proposed Solution

EchoGuard AI provides a single interface for request management and status monitoring. It uses predefined rules and keyword-based checks to assist with request categorisation, document-detail checking, and identifying overdue requests.

The application is designed to support students and faculty in reviewing request information and following up when necessary.

Features

- Student and teacher/faculty account-access options.
- College request creation and tracking.
- Request status monitoring.
- Dashboard summaries of request counts and statuses.
- Rule-based request-category suggestions.
- Checks for potentially missing details in supported text-based PDF documents.
- Date-based identification of overdue requests.
- Editable follow-up message suggestions, where implemented.

Technology Stack

- Programming Language: Python
- Web Framework and UI: Streamlit
- Data Processing: Pandas
- PDF Text Extraction: PyMuPDF
- Version Control and Repository: Git and GitHub
- Testing Framework: Pytest

How to Run Locally

Prerequisites

- Python installed on your computer.
- Git installed on your computer.
- The EchoGuard AI project repository.

Installation

1. Clone the repository:
   
   git clone YOUR_GITHUB_REPOSITORY_URL

2. Move into the project directory:
   
   cd EchoGuard-AI

3. Install the required dependencies:
   
   pip install -r requirements.txt

4. Start the Streamlit application:
   
   streamlit run app.py

5. Open the local URL displayed in your terminal.

Replace "app.py" with the actual entry-point filename if your project uses a different one.

AI Methodology

EchoGuard AI uses a transparent, rule-based approach to assist with college request management.

- Keyword Matching: Suggests request categories based on configured keywords.
- Document Detail Checking: Examines extracted text from supported PDF documents for potentially missing information.
- Date-Based Analysis: Uses predefined date rules to identify overdue requests.
- Follow-Up Assistance: Supports the preparation of editable follow-up messages, where implemented.

The analysis uses predefined rules rather than a trained machine-learning model.

Model and API Usage

- AI Method: Rule-based analysis and keyword matching.
- Trained Machine-Learning Model: Not used in the current rule-based implementation.
- External Generative AI Model: Not required for the current analysis features.
- External AI API: Not required for the rule-based analysis.
- Document Processing: PyMuPDF supports text extraction from compatible PDF files.

Working Product and Demo

- Live Application: https://echoguard---ai-z6wfqpcsabt2hjojcabwnx.streamlit.app/
- Demo Video: "Watch the EchoGuard AI Demo" (YOUR_DEMO_VIDEO_URL)

The live application and demonstration video showcase the user interface, request workflow, and main features of EchoGuard AI.

Project Status

EchoGuard AI is a working project developed to demonstrate college request management and rule-based request analysis. The live application provides access to the features available in the deployed version.

Privacy Notice

Use appropriate care when entering personal or institutional information. Demonstrations and screenshots should use fictional sample data rather than private student records or credentials.

Team Member Contributions

- Yogapriya — Team Lead, Front-End Developer, and UI/UX Designer
- Sarah — Back-End Developer
- Sangeetha — AI Engineering and Documentation
- Titiksha — Research
