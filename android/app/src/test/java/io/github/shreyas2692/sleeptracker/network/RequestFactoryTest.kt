package io.github.shreyas2692.sleeptracker.network

import io.github.shreyas2692.sleeptracker.model.NightDraft
import io.github.shreyas2692.sleeptracker.model.ServerConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RequestFactoryTest {
    private val config = ServerConfig("https://sleep.example.com/", "review", "secret")
    private val factory = RequestFactory(config)

    @Test
    fun healthIsPublicAndOtherRequestsUseBasicAuth() {
        assertFalse(factory.health().headers.containsKey("Authorization"))
        assertEquals("Basic cmV2aWV3OnNlY3JldA==", factory.stats().headers["Authorization"])
    }

    @Test
    fun formFieldsAreEncodedAndCrudRequestsExpectJson() {
        val request = factory.add(
            NightDraft("2026-07-30", "23:15", "07:00", 4, "good & calm"),
        )

        assertEquals("POST", request.method)
        assertEquals("https://sleep.example.com/add", request.url)
        assertEquals("XMLHttpRequest", request.headers["X-Requested-With"])
        assertEquals(
            "date=2026-07-30&bedtime=23%3A15&wake=07%3A00&quality=4&notes=good+%26+calm",
            request.body!!.toString(Charsets.UTF_8),
        )
    }

    @Test
    fun redirectResponsesAreAcceptedOnlyForRedirectBasedSettingsRoutes() {
        assertTrue(302 in factory.updateSettings("8", "23:00").additionalSuccessStatuses)
        assertTrue(303 in factory.clear().additionalSuccessStatuses)
        assertTrue(factory.add(NightDraft("2026-07-30", "23:00", "07:00", 4, ""))
            .additionalSuccessStatuses.isEmpty())
    }

    @Test
    fun releasePolicyRequiresHttps() {
        assertNull(ServerUrlPolicy.validate("HTTPS://sleep.example.com", allowInsecureLocal = false))
        assertTrue(ServerUrlPolicy.validate("http://10.0.2.2:5000", allowInsecureLocal = false)!!.contains("HTTPS"))
    }

    @Test
    fun debugPolicyAllowsOnlyLoopbackAndPrivateLanHttp() {
        listOf(
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "http://10.0.2.2:5000",
            "http://172.16.1.2",
            "http://192.168.1.4",
            "http://[fd00::1]:5000",
        ).forEach { assertNull("expected local: $it", ServerUrlPolicy.validate(it, true)) }

        listOf(
            "http://example.com",
            "http://10.evil.example",
            "http://fcorp.example",
            "http://172.32.0.1",
            "http://256.1.1.1",
        ).forEach { assertTrue("expected rejection: $it", ServerUrlPolicy.validate(it, true) != null) }
    }

    @Test
    fun originRejectsPathsCredentialsQueriesAndFragments() {
        listOf(
            "https://sleep.example.com/app",
            "https://owner:secret@sleep.example.com",
            "https://sleep.example.com?q=1",
            "https://sleep.example.com/#fragment",
        ).forEach { assertTrue(ServerUrlPolicy.validate(it, false) != null) }
    }
}
