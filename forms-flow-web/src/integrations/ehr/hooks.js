/**
 * React Hooks for EHR Integration
 * Provides easy-to-use hooks for integrating EHR functionality into React components
 */

import { useState, useEffect, useCallback } from 'react';
import { isEhrEnabled, getSMARTConfig, debugError, debugWarn } from './config';
import { launchSMART, fetchPatientData } from './service';
import { mapPatientToFormio } from './mapper';

/**
 * Hook to fetch and map patient data from EHR
 * Automatically handles SMART launch and patient data fetching
 * 
 * @param {Object} options - Configuration options
 * @param {Object} options.form - Form.io form schema (optional, for better field mapping)
 * @param {boolean} options.autoFetch - Whether to automatically fetch on mount (default: true)
 * @returns {Object} Hook result with patient data, loading state, and error
 */
export function useEhrPatientData({ form = null, autoFetch = true } = {}) {
  const [patientData, setPatientData] = useState(null);
  const [mappedData, setMappedData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    // Check if EHR is enabled
    if (!isEhrEnabled()) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Get SMART configuration
      const smartConfig = getSMARTConfig();
      
      if (!smartConfig.clientId) {
        debugWarn('EHR Integration: SMART client ID not configured and could not be extracted from token');
        setError('EHR integration is not properly configured');
        setLoading(false);
        return;
      }

      // Launch SMART client
      const smartClientPromise = launchSMART(
        smartConfig.clientId,
        smartConfig.redirectUri,
        smartConfig.scope
      );
      
      // Handle the promise - launchSMART may return null if no EHR context
      const fhirClient = await Promise.resolve(smartClientPromise);
      
      if (!fhirClient) {
        setLoading(false);
        return;
      }

      // Fetch patient data
      const data = await fetchPatientData(fhirClient);
      
      if (!data || !data.patient) {
        throw new Error('No patient data received from EHR');
      }

      // Store raw patient data
      setPatientData(data.patient);
      setError(null);
    } catch (err) {
      debugError('Error fetching patient data from EHR:', err);
      
      // Only set error if it's not a redirect/OAuth flow error
      const errorMessage = err.message || 'Failed to fetch patient data from EHR system';
      if (!errorMessage.includes('must be launched from Epic') && 
          !errorMessage.includes('redirect') && 
          !errorMessage.includes('OAuth')) {
        setError(errorMessage);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Map patient data to form fields whenever patient data or form changes
  useEffect(() => {
    if (patientData) {
      const mapped = mapPatientToFormio(patientData, form);
      
      // Filter out non-primitive values recursively to support nested components
      const deepFilter = (obj) => {
        if (obj === null || obj === undefined) return obj;
        if (typeof obj === 'object') {
          const result = {};
          Object.keys(obj).forEach(k => {
            const val = obj[k];
            if (val !== null && val !== undefined) {
              if (typeof val === 'object') {
                result[k] = deepFilter(val);
              } else {
                result[k] = typeof val === 'string' ? val : String(val);
              }
            }
          });
          return result;
        }
        return typeof obj === 'string' ? obj : String(obj);
      };
      
      const filteredMapped = deepFilter(mapped);
      setMappedData(filteredMapped);
    }
  }, [patientData, form]);

  useEffect(() => {
    if (autoFetch && isEhrEnabled()) {
      // Check URL parameters first and store them in sessionStorage if present
      const urlParams = new URLSearchParams(window.location.search);
      const urlIsEHR = urlParams.get('isEHR');
      const urlCode = urlParams.get('code');
      const urlState = urlParams.get('state');
      const urlIss = urlParams.get('iss');
      const urlLaunch = urlParams.get('launch');
      
      // Store URL parameters in sessionStorage if they exist
      if (urlIsEHR) {
        sessionStorage.setItem('epic_isEHR', urlIsEHR);
      }
      if (urlCode) {
        sessionStorage.setItem('epic_code', urlCode);
      }
      if (urlState) {
        sessionStorage.setItem('epic_state', urlState);
      }
      if (urlIss) {
        sessionStorage.setItem('epic_iss', urlIss);
      }
      if (urlLaunch) {
        sessionStorage.setItem('epic_launch', urlLaunch);
      }
      
      // Always attempt to fetch - let the service layer determine if EHR context exists
      // The service will return null gracefully if there's no EHR launch context
      fetchData();
    }
  }, [autoFetch, fetchData]);

  return {
    patientData,
    mappedData,
    loading,
    error,
    refetch: fetchData
  };
}
