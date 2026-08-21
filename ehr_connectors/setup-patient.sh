#!/bin/bash

PATIENT_ID="839737a4-5804-4adb-b645-740275239062"
BASE_URL="https://launch.smarthealthit.org/v/r4/fhir"

echo "=== Step 1: Create Patient ==="
curl -X PUT "$BASE_URL/Patient/$PATIENT_ID" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d '{
    "resourceType": "Patient",
    "id": "839737a4-5804-4adb-b645-740275239062",
    "meta": {
      "tag": [
        { "system": "https://smarthealthit.org/tags", "code": "synthea-5-2019" },
        { "system": "https://aletheamedical.com/fhir/tags", "code": "smart-launch-verified", "display": "Verified via Alethea SMART Launch" }
      ]
    },
    "identifier": [
      { "system": "https://github.com/synthetichealth/synthea", "value": "80a75b5a-fd30-4f38-895d-d8098fe7206e" },
      { "type": { "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR", "display": "Medical Record Number" }], "text": "Medical Record Number" }, "system": "http://hospital.smarthealthit.org", "value": "KKN-MR-2024-001" },
      { "type": { "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "SS", "display": "Social Security Number" }], "text": "Social Security Number" }, "system": "http://hl7.org/fhir/sid/us-ssn", "value": "999-12-3456" },
      { "type": { "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "DL", "display": "Drivers License" }], "text": "Drivers License" }, "system": "urn:oid:2.16.840.1.113883.4.3.25", "value": "KKN99912345" },
      { "type": { "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "PPN", "display": "Passport Number" }], "text": "Passport Number" }, "system": "http://standardhealthrecord.org/fhir/StructureDefinition/passportNumber", "value": "N1234567" }
    ],
    "name": [{ "use": "official", "family": "Nair", "given": ["Krishna", "Kumar"], "prefix": ["Mr."] }],
    "telecom": [
      { "system": "phone", "value": "555-123-4567", "use": "home" },
      { "system": "email", "value": "krishnakumar.nair@aot-technologies.com", "use": "work" }
    ],
    "gender": "male",
    "birthDate": "1990-06-15",
    "address": [{ "line": ["123 Tech Park Avenue Apt 5"], "city": "Thiruvananthapuram", "state": "Kerala", "postalCode": "695001", "country": "IN" }]
  }'

echo -e "\n\n=== Step 2: Create Encounter 1 - Office Visit ==="
curl -X POST "$BASE_URL/Encounter" \
  -H "Content-Type: application/fhir+json" \
  -d '{
    "resourceType": "Encounter",
    "status": "finished",
    "class": { "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "Ambulatory" },
    "type": [{ "text": "Office Visit" }],
    "subject": { "reference": "Patient/839737a4-5804-4adb-b645-740275239062" },
    "period": { "start": "2026-01-10T09:00:00Z", "end": "2026-01-10T09:30:00Z" }
  }'

echo -e "\n\n=== Step 3: Create Encounter 2 - Emergency Visit ==="
curl -X POST "$BASE_URL/Encounter" \
  -H "Content-Type: application/fhir+json" \
  -d '{
    "resourceType": "Encounter",
    "status": "finished",
    "class": { "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER", "display": "Emergency" },
    "type": [{ "text": "Emergency Room Visit" }],
    "subject": { "reference": "Patient/839737a4-5804-4adb-b645-740275239062" },
    "period": { "start": "2026-03-05T14:00:00Z", "end": "2026-03-05T16:45:00Z" }
  }'

echo -e "\n\n=== Step 4: Create Encounter 3 - Annual Checkup ==="
curl -X POST "$BASE_URL/Encounter" \
  -H "Content-Type: application/fhir+json" \
  -d '{
    "resourceType": "Encounter",
    "status": "in-progress",
    "class": { "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "Ambulatory" },
    "type": [{ "text": "Annual Checkup" }],
    "subject": { "reference": "Patient/839737a4-5804-4adb-b645-740275239062" },
    "period": { "start": "2026-06-24T10:00:00Z" }
  }'

echo -e "\n\n=== Step 5: List All Encounters for Patient ==="
curl "$BASE_URL/Encounter?patient=839737a4-5804-4adb-b645-740275239062"

echo -e "\n\nDone."
