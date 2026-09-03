<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0">
  <xsl:template match="/">
    <normalized>
      <source>oiw-map-fwd</source>
      <id><xsl:value-of select="upper-case(//id)"/></id>
    </normalized>
  </xsl:template>
</xsl:stylesheet>
