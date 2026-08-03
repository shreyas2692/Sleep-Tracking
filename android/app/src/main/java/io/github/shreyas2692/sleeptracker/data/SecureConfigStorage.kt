package io.github.shreyas2692.sleeptracker.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import io.github.shreyas2692.sleeptracker.model.ServerConfig
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class EncryptedValue(val ciphertext: ByteArray, val iv: ByteArray)

interface CredentialCipher {
    fun encrypt(value: ByteArray): EncryptedValue
    fun decrypt(value: EncryptedValue): ByteArray
}

interface ConfigPersistence {
    fun load(): ServerConfig
    fun save(config: ServerConfig)
}

class ConfigRepository(private val persistence: ConfigPersistence) {
    fun load(): ServerConfig = persistence.load()
    fun save(config: ServerConfig) = persistence.save(config)
}

class AndroidKeystoreCredentialCipher : CredentialCipher {
    private val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }

    override fun encrypt(value: ByteArray): EncryptedValue {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        return EncryptedValue(cipher.doFinal(value), cipher.iv)
    }

    override fun decrypt(value: EncryptedValue): ByteArray {
        val key = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
            ?: throw IllegalStateException("Credential key is unavailable")
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, value.iv))
        return cipher.doFinal(value.ciphertext)
    }

    @Synchronized
    private fun getOrCreateKey(): SecretKey {
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "sleep_tracker_server_password_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}

class AndroidConfigPersistence(
    context: Context,
    private val cipher: CredentialCipher = AndroidKeystoreCredentialCipher(),
) : ConfigPersistence {
    private val preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    override fun load(): ServerConfig {
        val credentials = try {
            val ciphertext = preferences.getString(KEY_CREDENTIALS, null)
            val iv = preferences.getString(KEY_IV, null)
            if (ciphertext == null || iv == null) {
                null
            } else {
                cipher.decrypt(
                    EncryptedValue(
                        Base64.decode(ciphertext, Base64.NO_WRAP),
                        Base64.decode(iv, Base64.NO_WRAP),
                    ),
                ).toString(Charsets.UTF_8).split(CREDENTIAL_SEPARATOR, limit = 2)
                    .takeIf { it.size == 2 }
            }
        } catch (_: Exception) {
            preferences.edit().remove(KEY_CREDENTIALS).remove(KEY_IV).apply()
            null
        }
        return ServerConfig(
            baseUrl = preferences.getString(KEY_URL, "") ?: "",
            username = credentials?.get(0) ?: "sleep",
            password = credentials?.get(1) ?: "",
        )
    }

    override fun save(config: ServerConfig) {
        require(CREDENTIAL_SEPARATOR !in config.username && CREDENTIAL_SEPARATOR !in config.password)
        val credentialBytes = (config.username.trim() + CREDENTIAL_SEPARATOR + config.password)
            .toByteArray(Charsets.UTF_8)
        val encrypted = cipher.encrypt(credentialBytes)
        val editor = preferences.edit()
            .putString(KEY_URL, config.normalizedBaseUrl)
            .putString(KEY_CREDENTIALS, Base64.encodeToString(encrypted.ciphertext, Base64.NO_WRAP))
            .putString(KEY_IV, Base64.encodeToString(encrypted.iv, Base64.NO_WRAP))
        check(editor.commit()) { "Could not persist server configuration" }
    }

    private companion object {
        const val PREFS_NAME = "secure_server_configuration"
        const val KEY_URL = "base_url"
        const val KEY_CREDENTIALS = "credentials_ciphertext"
        const val KEY_IV = "credentials_iv"
        const val CREDENTIAL_SEPARATOR = '\u0000'
    }
}
