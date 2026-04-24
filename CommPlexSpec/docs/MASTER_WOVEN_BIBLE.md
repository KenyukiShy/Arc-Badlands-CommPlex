# CommPlex Sovereign: Operational Bible
**Version:** 6.0 (Diamond Edition)  
**Author:** Lead Systems Architect, CommPlex Sovereign  
**Date:** April 22, 2026

***

## Foreword

This document serves as the Operational Bible for the CommPlex Sovereign (V6.0) architecture. The Sovereign Matrix is officially built, Git-controlled, and active. We are moving from the architectural phase into the execution sprint. This bible outlines the critical systems, their configurations, and the operational workflows that define our platform.

The architecture is a distributed system composed of several core platforms: **Claude** for project-based AI development, **Audry/Bland.ai** as our primary agent and automation control plane, **Twilio** for the telephony and communications backbone, and **GCP/Vertex** for foundational AI models and cloud infrastructure.

This manual is the single source of truth for all teams. Adherence to these protocols is mandatory to ensure system integrity, prevent cross-domain contamination, and maintain operational excellence.

<p align='center'><img src='23_Audry_Active_Agents.png' width='600'></p>

***
<br>

## I. Claude System: Core Project Environment

The Claude environment is where we bootstrap our isolated AI projects. This isolation is a critical security and stability measure, preventing cross-contamination between different AI domains.

### 1.1. Project Bootstrapping Protocol

All team members receive domain-specific ZIP packages. The initial setup requires creating a fresh Claude Project and uploading the concatenated `.txt` file found within the package. This procedure instantiates the project with its required foundational context.

<p align='center'><img src='01a_Claude_Project_Dashboard.png' width='600'></p>

### 1.2. Project Creation

The first step in the bootstrapping process is creating a new, named personal project within the Claude console. This creates the container for all subsequent artifacts, chats, and configurations.

<p align='center'><img src='30c_Twilio_Active_Numbers.png' width='600'></p>

### 1.3. Project Workspace & Context Management

Once a project is created, its workspace is used to manage context. This includes adding permanent instructions to tailor Claude's responses and uploading reference files (PDFs, documents) that the AI will use for knowledge retrieval.

<p align='center'><img src='30d_Twilio_A2P_Campaign.png' width='600'></p>

### 1.4. Project Interaction Interface

The primary interface for working within a project is the chat view. This is where development, testing, and interaction with the configured AI occur. All conversations are organized and leverage the established project knowledge.

<p align='center'><img src='30e_Twilio_SIP_Origination.png' width='600'></p>

***
<br>

## II. Audry / Bland.ai: Agent & Automation Platform

Bland.ai serves as our primary control plane for defining, deploying, and monitoring AI agents. Our flagship persona, 'Audry Harper', is managed entirely within this system.

### 2.1. Persona Configuration: 'Audry Harper'

This is the central cockpit for the 'Audry Harper' persona. Here, we define its core identity (name, voice, role), modalities (voice, SMS), and apply high-level compliance policies (Guard Rails). All changes are version-controlled and must be promoted to production.

<p align='center'><img src='01_Claude_Cockpit_Init.png' width='600'></p>

### 2.2. Automation Workflow: Trigger Configuration

Workflows are initiated by triggers. This interface allows us to define event-based triggers (e.g., 'Lead Created' from a CRM) that will execute a corresponding action, such as initiating a call with the Audry persona.

<p align='center'><img src='02b_Claude_Ingestion_Log.png' width='600'></p>

### 2.3. Persona Knowledge & Tool Integration

A persona's capabilities are extended by connecting it to knowledge bases and external tools. This screen shows the 'Audry' persona connected to the `AutoBäad Vehicles Knowledge Base` and the `Evaluate Vehicle Offer` tool, allowing it to access data and perform actions beyond its base programming.

<p align='center'><img src='03_Audry_Triage_Logic.png' width='600'></p>

### 2.4. Tool Logic Editor

External tools are powered by custom JavaScript code. This editor is where we define the tool's input variables (e.g., `offer_amount`, `vehicle_target`) and write the server-side logic that runs during a call to process these variables and return a result.

<p align='center'><img src='41_Hazen_Thermal_Limits.png' width='600'></p>

### 2.5. Post-Conversation Analysis & Webhooks

For each persona, we can configure post-conversation actions. This includes automated call summarization, structured data extraction, and webhook configurations. A webhook URL can be specified to receive a POST request with the full call details upon completion.

<p align='center'><img src='04_Audry_Pricing_MKZ.png' width='600'></p>

### 2.6. System Alert Configuration

We must proactively monitor system health. This interface is used to create alerts based on performance (latency), quality (API errors), or custom experience metrics. Thresholds are set to trigger notifications when certain conditions are met over a specified time period.

<p align='center'><img src='05_Audry_Qualification_Node.png' width='600'></p>

### 2.7. Compliance & Policy Management (Guard Rails)

The Compliance dashboard is where we define and manage Guard Rails. This includes built-in policies like TCPA monitoring and enterprise features like Watchtower for testing inconsistencies. Custom guard rails can be established to enforce organization-specific rules.

<p align='center'><img src='07_Audry_Edge_Pricing.png' width='600'></p>

### 2.8. Call Log Monitoring

This dashboard is the central repository for all call logs. It provides a detailed, filterable view of completed and active calls, including direction, duration, status, and associated metadata. This is a primary tool for debugging and operational analysis.

<p align='center'><img src='06_Audry_Webhook_Payload.png' width='600'></p>

### 2.9. Knowledge Base Management

The Knowledge Base is a structured data store for our agents. The `SOURCES` tab allows for viewing and editing the raw data, which is version-controlled. The `TEST` tab provides an interface to query the knowledge base and see how the agent will respond, ensuring accuracy.

<p align='center'><img src='24_Twilio_SIP_Domains.png' width='600'></p>
<p align='center'><img src='25_Twilio_A2P_10DLC.png' width='600'></p>

### 2.10. Telephony & Messaging Dashboards

The platform includes dedicated dashboards for managing telephony and SMS. The Phone Numbers dashboard is for purchasing and activating new inbound numbers. The SMS dashboard provides an overview of all text message conversations.

<p align='center'><img src='32_GCP_SA_Keys.png' width='600'></p>
<p align='center'><img src='40_Onde_Wave_Deployment.png' width='600'></p>

### 2.11. Manual Call Initiation

The `Send Call` interface allows for placing single, ad-hoc outbound calls. This is primarily used for testing and debugging. It provides a UI to configure the phone number, voice, prompt, and model settings, and it also generates the corresponding API request code.

<p align='center'><img src='31_GCP_IAM_Roles.png' width='600'></p>

### 2.12. SIP Trunk Configuration

Connecting our system via SIP is a multi-step process managed within the Bland.ai dashboard.
1.  **Select Type:** Choose between Inbound or Outbound SIP configuration.
2.  **Assign Numbers:** Add or select the E.164 formatted numbers that will receive inbound SIP calls.
3.  **Define Endpoint:** Configure the SIP endpoint (server) details, transport protocol, and any custom headers.
4.  **Finalize Configuration:** Once saved, the system provides a summary, including firewall IP whitelisting rules and port information.

<p align='center'><img src='26_Twilio_Messaging_Service.png' width='600'></p>
<p align='center'><img src='27_Twilio_Regulatory_Bundle.png' width='600'></p>
<p align='center'><img src='33_GCP_Vertex_Quotas.png' width='600'></p>
<p align='center'><img src='42_Onde_Execution_Logs.png' width='600'></p>
<p align='center'><img src='34_GCP_IAM_Overview.png' width='600'></p>
<p align='center'><img src='43_Onde_Observer_Pattern.png' width='600'></p>

### 2.13. Organization API Key Management

Platform-level API keys for programmatic access to the Bland.ai organization are managed here. These keys are distinct from individual user credentials and should be handled with strict security protocols.

<p align='center'><img src='28_Twilio_Webhook_Config.png' width='600'></p>

***
<br>

## III. Twilio: Communications Backbone

Twilio serves as our fundamental communications backbone, providing the infrastructure for telephony, messaging, and regulatory compliance.

### 3.1. Credential Management: API Keys & Auth Tokens

The Twilio console is the source for our primary and test credentials. This includes the Account SID, Auth Tokens, and revocable API Keys used to authenticate all REST API requests and sign Access Tokens for our real-time SDKs. These credentials must be stored securely in our vault.

<p align='center'><img src='10_Audry_Transfer_Logic.png' width='600'></p>
<p align='center'><img src='38_GCP_Vertex_Endpoints.png' width='600'></p>

### 3.2. General Account Settings

This section of the Twilio console contains high-level account settings, including the Account Name, Account SID, and critical security configurations such as SSL certificate validation for all Twilio-originated webhooks.

<p align='center'><img src='30b_Twilio_Rate_Limits.png' width='600'></p>

### 3.3. Active Phone Number Management

All active phone numbers provisioned in our account are managed here. This dashboard shows a number's capabilities (Voice, SMS, MMS) and its active configuration, such as the Voice Webhook URL that Twilio will POST to when a call is received.

<p align='center'><img src='30_Twilio_SIP_Termination.png' width='600'></p>
<p align='center'><img src='13_Audry_Fallback_Routing.png' width='600'></p>

### 3.4. SIP Domain Configuration

To direct SIP traffic toward Twilio Programmable Voice, we must configure SIP Domains. This involves defining a unique SIP URI, setting up authentication (IP ACLs, Credential Lists), and specifying the Call Control Configuration (e.g., Webhooks) that Twilio invokes upon receiving a SIP INVITE.

<p align='center'><img src='29_Twilio_Log_Trace.png' width='600'></p>

### 3.5. Regulatory Compliance & Bundles

To operate legally in various regions, we must manage regulatory compliance. This involves creating and managing physical addresses and bundling them with supporting documentation into Regulatory Bundles. These bundles are then associated with phone numbers to meet country-specific requirements.

<p align='center'><img src='35_GCP_Audit_Logs.png' width='600'></p>
<p align='center'><img src='44_Hazen_Hardware_Telemetry.png' width='600'></p>
<p align='center'><img src='36_GCP_Network_Rules.png' width='600'></p>
<p align='center'><img src='45_Hazen_GPU_Load.png' width='600'></p>
<p align='center'><img src='37_GCP_Masking_Logic.png' width='600'></p>

***
<br>

## IV. GCP / Vertex: Cloud Infrastructure & Foundational Models

Google Cloud Platform (GCP) and its Vertex/AI Studio services provide the underlying cloud infrastructure, foundational AI models (Gemini), and developer tools for our system.

### 4.1. Account Authentication & Project Selection

Access to all Google Cloud resources begins with standard Google account authentication. Once authenticated, the GCP console allows for selection of the active project, such as `CommPlex`, which scopes all subsequent actions and resource views.

<p align='center'><img src='18_Audry_Extract_Data.png' width='600'></p>
<p align='center'><img src='20_Audry_Send_Webhook.png' width='600'></p>
<p align='center'><img src='08_Audry_Call_Routing.png' width='600'></p>

### 4.2. Gemini API Billing & Tiers

Financial management for the Gemini API is handled in the Google AI Studio billing section. This dashboard shows the current billing account, associated projects, usage tier, and criteria for upgrading to higher tiers. A prepayment method is required for all API usage.

<p align='center'><img src='01c_Claude_System_Prompts.png' width='600'></p>

### 4.3. Gemini API Key Management

API keys for the Gemini API are managed within Google AI Studio. This interface allows for creating new keys, viewing the details of existing keys (including associated project information), and revoking access. It's critical to note that permission errors can prevent keys from being listed.

<p align='center'><img src='02c_Claude_Format_Rules.png' width='600'></p>
<p align='center'><img src='39_GCP_SA_Metrics.png' width='600'></p>
<p align='center'><img src='22_Audry_End_Call_Logic.png' width='600'></p>

### 4.4. GCP Service Account Key Management

For programmatic, non-user-based authentication to GCP resources, we use Service Accounts. The IAM & Admin console is where we manage the keys for these accounts. Downloading a private key (`.json` file) poses a security risk and must be handled with extreme care, storing it securely in the project vault.

<p align='center'><img src='15_Audry_Post_Call_Hooks.png' width='600'></p>

### 4.5. Agent Platform Studio

The Agent Platform Studio is a multimodal development environment within GCP for building sophisticated agents and applications. It provides access to Google's most advanced models (Gemini, Veo) and a low-code interface for agent design.

<p align='center'><img src='39b_GCP_Agent_Studio.png' width='600'></p>

### 4.6. API Documentation & Regional Availability

The official developer documentation (`ai.google.dev`) is the source of truth for all API specifications, including regional availability for Google AI Studio and the Gemini API. All developers must be familiar with these resources.

<p align='center'><img src='19_Audry_Pathway_Nodes.png' width='600'></p>
<p align='center'><img src='21_Audry_Global_Knowledge.png' width='600'></p>

### 4.7. Local Development Environment & SDK Integration

Development and scripting occur in a local ChromeOS Linux environment. It is critical to properly configure file sharing between ChromeOS and the Linux VM to ensure scripts can access necessary files (e.g., project artifacts, API keys). The provided documentation and scripts utilize the `google-genai` Python SDK to interact with the backend services. Troubleshooting file access errors is a common first step.

<p align='center'><img src='47_Twilio_SIP_Origination.png' width='600'></p>
<p align='center'><img src='17_Audry_API_Response.png' width='600'></p>
<p align='center'><img src='45b_Onde_Agent_Deployment.png' width='600'></p>