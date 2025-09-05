{
  "openapi": "3.1.0",
  "info": {
    "title": "FIRST Countries API",
    "version": "1.0.0",
    "description": "Lists all countries and their regions indexed by two-letter country codes (ISO 3166-1)."
  },
  "servers": [
    {
      "url": "https://api.first.org/data/v1",
      "description": "FIRST API v1"
    }
  ],
  "paths": {
    "/countries": {
      "get": {
        "summary": "Get list of countries",
        "description": "Lists all countries and their regions, indexed by two-letter country codes.",
        "parameters": [
          {
            "name": "region",
            "in": "query",
            "description": "Filter by region of the country.",
            "required": false,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "q",
            "in": "query",
            "description": "Free text search at the country name, abbreviations, and region.",
            "required": false,
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "limit",
            "in": "query",
            "description": "Number of results to return.",
            "required": false,
            "schema": {
              "type": "integer",
              "default": 100
            }
          },
          {
            "name": "offset",
            "in": "query",
            "description": "Offset of the first result to return.",
            "required": false,
            "schema": {
              "type": "integer",
              "default": 0
            }
          },
          {
            "name": "pretty",
            "in": "query",
            "description": "Pretty-print the JSON output.",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            }
          },
          {
            "name": "access",
            "in": "query",
            "description": "Scope of the data: public, iso, or full.",
            "required": false,
            "schema": {
              "type": "string",
              "enum": ["public", "iso", "full"],
              "default": "public"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "A JSON object containing countries and regions",
            "content": {
              "application/json": {
                "example": {
                  "status": "OK",
                  "status-code": 200,
                  "version": "1",
                  "total": 57,
                  "limit": 3,
                  "offset": 0,
                  "access": "public",
                  "data": {
                    "DZ": {
                      "country": "Algeria",
                      "region": "Africa"
                    },
                    "AO": {
                      "country": "Angola",
                      "region": "Africa"
                    },
                    "BJ": {
                      "country": "Benin",
                      "region": "Africa"
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
