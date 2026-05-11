// validation-utils.js
/**
 * Shared validation utilities for the application.
 * Use these functions instead of duplicating validation logic across files.
 */

const ValidationUtils = {
    /**
     * Validates if a string is a properly formatted GUID/UUID.
     * @param {string} guid - The GUID string to validate
     * @returns {boolean} True if valid GUID format, false otherwise
     */
    validateGuid: function(guid) {
        const guidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        return guidRegex.test(guid);
    },

    /**
     * Validates if a string is a properly formatted email address.
     * @param {string} email - The email string to validate
     * @returns {boolean} True if valid email format, false otherwise
     */
    validateEmail: function(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }
};
